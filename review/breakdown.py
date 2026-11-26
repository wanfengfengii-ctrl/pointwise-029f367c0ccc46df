from dataclasses import asdict, dataclass

from review.roster_results import SeatResult
from submission.receipts import CATEGORIES


@dataclass(frozen=True)
class CategoryTotals:
    count: int = 0
    points: int = 0
    correct: int = 0

    def with_answer(self, score):
        return CategoryTotals(
            self.count + 1, self.points + score.points, self.correct + int(score.correct),
        )

    def to_dict(self):
        return asdict(self)


def summarize_results(rows: tuple[SeatResult, ...]) -> dict[str, CategoryTotals]:
    totals = {category: CategoryTotals() for category in CATEGORIES}
    for row in rows:
        if row.receipt is not None:
            receipt = row.receipt
            totals[receipt.category] = totals[receipt.category].with_answer(receipt.score)
    return totals
