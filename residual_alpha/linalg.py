"""Small dense linear-algebra helpers for modest factor models."""

from __future__ import annotations


def solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve Ax=b using Gaussian elimination with partial pivoting."""
    n = len(vector)
    augmented = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            raise ValueError("singular matrix")
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        scale = augmented[col][col]
        augmented[col] = [value / scale for value in augmented[col]]
        for row in range(n):
            if row == col:
                continue
            scale = augmented[row][col]
            if scale:
                augmented[row] = [
                    left - scale * right
                    for left, right in zip(augmented[row], augmented[col])
                ]
    return [augmented[i][-1] for i in range(n)]


def ridge_coefficients(
    observations: list[tuple[list[float], float]], ridge: float
) -> list[float]:
    size = len(observations[0][0])
    gram = [[0.0] * size for _ in range(size)]
    target = [0.0] * size
    for features, response in observations:
        for i in range(size):
            target[i] += features[i] * response
            for j in range(size):
                gram[i][j] += features[i] * features[j]
    for i in range(size):
        gram[i][i] += ridge
    return solve(gram, target)


def neutralize(
    raw: list[float], exposures: list[list[float]], ridge: float = 1e-8
) -> list[float]:
    """Project weights away from the rows of an exposure matrix."""
    if not raw or not exposures:
        return raw[:]
    factors = len(exposures)
    gram = [[0.0] * factors for _ in range(factors)]
    projection = [0.0] * factors
    for i in range(factors):
        projection[i] = sum(x * w for x, w in zip(exposures[i], raw))
        for j in range(factors):
            gram[i][j] = sum(x * y for x, y in zip(exposures[i], exposures[j]))
        gram[i][i] += ridge
    multipliers = solve(gram, projection)
    return [
        weight
        - sum(multipliers[factor] * exposures[factor][asset] for factor in range(factors))
        for asset, weight in enumerate(raw)
    ]

