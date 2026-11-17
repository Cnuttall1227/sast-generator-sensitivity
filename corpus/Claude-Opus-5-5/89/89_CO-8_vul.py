import os
from datetime import date
from typing import List, Optional

import strawberry
import uvicorn
from peewee import (
    BooleanField, CharField, DateField, ForeignKeyField, IntegerField, Model, SqliteDatabase,
)
from strawberry.asgi import GraphQL

DB_PATH = os.environ.get("ARCHIVE_DB", "/srv/film-archive/archive.db")
MAX_RESULTS = 50

database = SqliteDatabase(DB_PATH, pragmas={"journal_mode": "wal", "foreign_keys": 1})


class BaseModel(Model):
    class Meta:
        database = database


class Director(BaseModel):
    name = CharField(unique=True)
    born = DateField(null=True)


class Film(BaseModel):
    title = CharField(index=True)
    year = IntegerField()
    runtime_minutes = IntegerField()
    director = ForeignKeyField(Director, backref="films")
    restored = BooleanField(default=False)
    reel_count = IntegerField(default=1)


@strawberry.type
class DirectorType:
    id: int
    name: str
    born: Optional[date]


@strawberry.type
class FilmType:
    id: int
    title: str
    year: int
    runtime_minutes: int
    restored: bool
    reel_count: int
    director: DirectorType


def to_film_type(film):
    return FilmType(
        id=film.id,
        title=film.title,
        year=film.year,
        runtime_minutes=film.runtime_minutes,
        restored=film.restored,
        reel_count=film.reel_count,
        director=DirectorType(id=film.director.id, name=film.director.name, born=film.director.born),
    )


def films_with_title_prefix(prefix, restored_only):
    restored_clause = "AND f.restored = 1" if restored_only else ""
    query = Film.raw(
        "SELECT f.* FROM film f "
        f"WHERE f.title LIKE '{prefix}%' {restored_clause} "
        f"ORDER BY f.title LIMIT {MAX_RESULTS}"
    )
    return [to_film_type(film) for film in query]


@strawberry.type
class Query:
    @strawberry.field
    def film(self, id: int) -> Optional[FilmType]:
        film = Film.get_or_none(Film.id == id)
        return to_film_type(film) if film else None

    @strawberry.field
    def films_by_year(self, year: int) -> List[FilmType]:
        films = Film.select().where(Film.year == year).order_by(Film.title).limit(MAX_RESULTS)
        return [to_film_type(f) for f in films]

    @strawberry.field
    def search_titles(self, prefix: str, restored_only: bool = False) -> List[FilmType]:
        prefix = prefix.strip()
        if len(prefix) < 2:
            raise ValueError("Search with at least two characters")
        return films_with_title_prefix(prefix[:60], restored_only)

    @strawberry.field
    def directors(self) -> List[DirectorType]:
        return [DirectorType(id=d.id, name=d.name, born=d.born) for d in Director.select().order_by(Director.name)]


@strawberry.type
class Mutation:
    @strawberry.mutation
    def mark_restored(self, id: int, reel_count: Optional[int] = None) -> Optional[FilmType]:
        film = Film.get_or_none(Film.id == id)
        if film is None:
            return None
        film.restored = True
        if reel_count is not None:
            if not 1 <= reel_count <= 50:
                raise ValueError("reel_count must be between 1 and 50")
            film.reel_count = reel_count
        film.save()
        return to_film_type(film)


schema = strawberry.Schema(query=Query, mutation=Mutation)
graphql_app = GraphQL(schema, graphql_ide=None)


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                database.connect(reuse_if_open=True)
                database.create_tables([Director, Film])
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                if not database.is_closed():
                    database.close()
                await send({"type": "lifespan.shutdown.complete"})
                return
    await graphql_app(scope, receive, send)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))