import io
import os

import joblib
import numpy as np
import pandas as pd
import streamlit as st
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score
import skops.io as sio

HOLDOUT_PATH = os.environ.get("LEADERBOARD_HOLDOUT", "/srv/leaderboard/holdout.csv")
LEADERBOARD_PATH = os.environ.get("LEADERBOARD_FILE", "/srv/leaderboard/scores.csv")
TARGET_COLUMN = "churned"
MAX_MODEL_BYTES = 50 * 1024 * 1024
TRUSTED_MODULE_PREFIXES = ("sklearn.", "numpy.", "scipy.sparse.")

st.set_page_config(page_title="Churn model leaderboard", layout="centered")


@st.cache_data
def load_holdout():
    frame = pd.read_csv(HOLDOUT_PATH)
    features = frame.drop(columns=[TARGET_COLUMN])
    return features, frame[TARGET_COLUMN].to_numpy()


def load_leaderboard():
    if os.path.exists(LEADERBOARD_PATH):
        return pd.read_csv(LEADERBOARD_PATH)
    return pd.DataFrame(columns=["team", "model", "f1", "accuracy", "submitted"])


def save_score(team, model_name, scores):
    board = load_leaderboard()
    row = {"team": team, "model": model_name, "f1": round(scores["f1"], 4),
           "accuracy": round(scores["accuracy"], 4), "submitted": pd.Timestamp.now().isoformat(timespec="minutes")}
    board = pd.concat([board, pd.DataFrame([row])], ignore_index=True)
    os.makedirs(os.path.dirname(LEADERBOARD_PATH), exist_ok=True)
    board.to_csv(LEADERBOARD_PATH, index=False)


def load_submitted_model(uploaded_bytes):
    try:
        unknown_types = sio.get_untrusted_types(data=uploaded_bytes)
    except Exception as exc:
        raise ValueError("upload a model saved with skops.io.dump (.skops file)") from exc
    rejected = [t for t in unknown_types if not t.startswith(TRUSTED_MODULE_PREFIXES)]
    if rejected:
        raise ValueError(f"the model uses types that aren't allowed: {', '.join(sorted(rejected)[:5])}")
    model = sio.loads(uploaded_bytes, trusted=unknown_types)
    if not hasattr(model, "predict"):
        raise ValueError("the file doesn't contain a model with a predict() method")
    return model


def score_model(model, features, labels):
    predictions = np.asarray(model.predict(features))
    if predictions.shape[0] != labels.shape[0]:
        raise ValueError("the model returned the wrong number of predictions")
    predictions = predictions.astype(int)
    return {
        "accuracy": accuracy_score(labels, predictions),
        "precision": precision_score(labels, predictions, zero_division=0),
        "recall": recall_score(labels, predictions, zero_division=0),
        "f1": f1_score(labels, predictions, zero_division=0),
        "confusion": confusion_matrix(labels, predictions, labels=[0, 1]),
    }


def main():
    st.title("Churn model leaderboard")
    st.write("Upload a trained scikit-learn pipeline saved with `joblib.dump`. "
             "It will be scored on the hidden holdout set.")
    team = st.text_input("Team name", max_chars=40).strip()
    uploaded = st.file_uploader("Model file (.joblib)", type=["joblib", "pkl"])

    if uploaded is not None and team:
        if uploaded.size > MAX_MODEL_BYTES:
            st.error("That model file is larger than 50 MB.")
            return
        features, labels = load_holdout()
        try:
            with st.spinner("Loading and scoring your model…"):
                model = load_submitted_model(uploaded.getvalue())
                scores = score_model(model, features, labels)
        except Exception as exc:
            st.error(f"Could not score the model: {type(exc).__name__}: {exc}")
            return
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("F1", f"{scores['f1']:.3f}")
        col2.metric("Accuracy", f"{scores['accuracy']:.3f}")
        col3.metric("Precision", f"{scores['precision']:.3f}")
        col4.metric("Recall", f"{scores['recall']:.3f}")
        st.write("Confusion matrix (rows: actual, columns: predicted)")
        st.dataframe(pd.DataFrame(scores["confusion"], index=["stayed", "churned"], columns=["stayed", "churned"]))
        if st.button("Submit to leaderboard"):
            save_score(team, uploaded.name, scores)
            st.success("Score submitted.")
    elif uploaded is not None:
        st.info("Enter your team name to score the model.")

    st.subheader("Leaderboard")
    board = load_leaderboard()
    if board.empty:
        st.write("No submissions yet.")
    else:
        st.dataframe(board.sort_values("f1", ascending=False).head(20), hide_index=True, use_container_width=True)


main()