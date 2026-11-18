import logging

import gradio as gr
import sympy as sp

MAX_INPUT_LENGTH = 200
x, y = sp.symbols("x y")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("algebra-checker")

EXERCISES = {
    "Expand (x + 3)(x - 2)": {"start": "(x + 3)*(x - 2)", "goal": "expand"},
    "Factor x^2 - 9": {"start": "x**2 - 9", "goal": "factor"},
    "Simplify (x^2 - 1)/(x - 1)": {"start": "(x**2 - 1)/(x - 1)", "goal": "simplify"},
    "Expand (2x + y)^2": {"start": "(2*x + y)**2", "goal": "expand"},
}


def parse_student_expression(text):
    cleaned = text.strip().replace("^", "**")
    if not cleaned:
        raise ValueError("Type your answer first.")
    if len(cleaned) > MAX_INPUT_LENGTH:
        raise ValueError("That answer is too long.")
    return sp.sympify(cleaned, locals={"x": x, "y": y})


def is_expanded(expr):
    return sp.expand(expr) == expr


def is_factored(expr):
    return sp.factor(expr) == expr or isinstance(expr, sp.Mul)


def check_answer(exercise_name, answer_text):
    exercise = EXERCISES.get(exercise_name)
    if exercise is None:
        return "Pick an exercise first.", ""
    start = sp.sympify(exercise["start"], locals={"x": x, "y": y})
    try:
        answer = parse_student_expression(answer_text)
    except ValueError as exc:
        return str(exc), ""
    except (sp.SympifyError, SyntaxError, TypeError):
        return "I couldn't read that. Use * for multiplication, e.g. 2*x.", ""

    if sp.simplify(answer - start) != 0:
        hint = f"Not equal to the original expression. Try checking a value: at x=2 the original is {start.subs({x: 2, y: 1})}."
        return "❌ Not quite.", hint

    goal = exercise["goal"]
    if goal == "expand" and not is_expanded(answer):
        return "➖ Equal, but not fully expanded yet.", "Multiply out every bracket."
    if goal == "factor" and not is_factored(answer):
        return "➖ Equal, but not factored.", "Look for a difference of squares or a common factor."
    if goal == "simplify" and sp.count_ops(answer) > sp.count_ops(sp.simplify(start)):
        return "➖ Equal, but it can be simpler.", "Cancel any common factors."
    log.info("Correct answer for %s", exercise_name)
    return "✅ Correct!", f"Rendered: {sp.latex(answer)}"


def show_exercise(exercise_name):
    exercise = EXERCISES.get(exercise_name)
    if exercise is None:
        return ""
    start = sp.sympify(exercise["start"], locals={"x": x, "y": y})
    return f"$$ {sp.latex(start)} $$"


with gr.Blocks(title="Algebra step checker") as demo:
    gr.Markdown("# Algebra step checker\nPick an exercise, type your answer, and check it.")
    exercise = gr.Dropdown(choices=list(EXERCISES), label="Exercise", value=list(EXERCISES)[0])
    problem = gr.Markdown(show_exercise(list(EXERCISES)[0]))
    answer = gr.Textbox(label="Your answer", placeholder="e.g. x**2 + x - 6", max_lines=1)
    check = gr.Button("Check")
    verdict = gr.Markdown()
    hint = gr.Markdown()
    exercise.change(show_exercise, inputs=exercise, outputs=problem)
    check.click(check_answer, inputs=[exercise, answer], outputs=[verdict, hint])
    answer.submit(check_answer, inputs=[exercise, answer], outputs=[verdict, hint])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)