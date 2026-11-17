# SPDX-License-Identifier: Apache-2.0
"""Train and evaluate micro-Doppler classifiers (report section 8.7).

* Candidates: k-nearest neighbours, RBF SVM, random forest, small MLP.
  Features are standardised using training data only (inside the pipeline).
* Model selection uses grouped cross-validation by session on the
  development sessions.
* The final score comes from later sessions that were never used for
  training or selection, with a bootstrap 95% confidence interval.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from sklearn.base import ClassifierMixin
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import GroupKFold, cross_val_score
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from dragonfly.classify.dataset import Dataset


def candidates(seed: int = 0) -> dict[str, Pipeline]:
    def pipe(model: ClassifierMixin) -> Pipeline:
        return make_pipeline(StandardScaler(), model)

    return {
        "knn": pipe(KNeighborsClassifier(n_neighbors=7)),
        "svm": pipe(SVC(kernel="rbf", C=3.0, gamma="scale")),
        "random_forest": pipe(RandomForestClassifier(n_estimators=200, random_state=seed)),
        "mlp": pipe(MLPClassifier(hidden_layer_sizes=(32, 16), max_iter=2000, random_state=seed)),
    }


@dataclass(frozen=True)
class Evaluation:
    model: str
    cv_accuracy: dict[str, float]
    test_accuracy: float
    test_ci95: tuple[float, float]
    precision: tuple[float, ...]
    recall: tuple[float, ...]
    confusion: npt.NDArray[np.int64]
    test_sessions: tuple[int, ...]


def bootstrap_ci(
    y_true: npt.NDArray[np.int64],
    y_pred: npt.NDArray[np.int64],
    groups: npt.NDArray[np.int64],
    n: int = 1000,
    seed: int = 0,
) -> tuple[float, float]:
    """95% interval for accuracy, resampling whole clips (not windows), since
    windows from the same clip are correlated."""
    rng = np.random.default_rng(seed)
    ids = np.unique(groups)
    accs = []
    for _ in range(n):
        pick = rng.choice(ids, size=len(ids), replace=True)
        idx = np.concatenate([np.flatnonzero(groups == g) for g in pick])
        accs.append(float(np.mean(y_true[idx] == y_pred[idx])))
    lo, hi = np.percentile(accs, [2.5, 97.5])
    return float(lo), float(hi)


def evaluate(ds: Dataset, test_sessions: Sequence[int], seed: int = 0) -> Evaluation:
    test = np.isin(ds.session, test_sessions)
    dev = ~test
    if not dev.any() or not test.any():
        raise ValueError("need both development and test sessions")
    n_dev_sessions = len(np.unique(ds.session[dev]))
    cv = GroupKFold(n_splits=min(4, n_dev_sessions))
    scores: dict[str, float] = {}
    models = candidates(seed)
    for name, model in models.items():
        s = cross_val_score(model, ds.X[dev], ds.y[dev], groups=ds.session[dev], cv=cv)
        scores[name] = float(np.mean(s))
    best = max(scores, key=lambda k: scores[k])
    final = models[best].fit(ds.X[dev], ds.y[dev])
    pred = final.predict(ds.X[test])
    p, r, _, _ = precision_recall_fscore_support(ds.y[test], pred, zero_division=0)
    return Evaluation(
        model=best,
        cv_accuracy=scores,
        test_accuracy=float(accuracy_score(ds.y[test], pred)),
        test_ci95=bootstrap_ci(ds.y[test], pred, ds.clip[test], seed=seed),
        precision=tuple(float(v) for v in p),
        recall=tuple(float(v) for v in r),
        confusion=confusion_matrix(ds.y[test], pred),
        test_sessions=tuple(test_sessions),
    )


class MajorityVote:
    """Smooth live labels with a majority vote over the last ``n`` windows."""

    def __init__(self, n: int = 5) -> None:
        if n < 1:
            raise ValueError("n must be at least 1")
        self._recent: deque[int] = deque(maxlen=n)

    def update(self, label: int) -> int:
        self._recent.append(label)
        return Counter(self._recent).most_common(1)[0][0]
