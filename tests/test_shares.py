import pytest

from app.services import allocate_shares


def rows(count: int) -> list[dict[str, object]]:
    return [
        {"offer_id": index + 1, "name": f"Offer {index + 1}", "state": "active"}
        for index in range(count)
    ]


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, []), (1, [100]), (3, [34, 33, 33]), (4, [25, 25, 25, 25]), (5, [20] * 5)],
)
def test_allocate_shares(count: int, expected: list[int]) -> None:
    assert [item["share"] for item in allocate_shares(rows(count))] == expected


def test_removed_rows_receive_zero_and_do_not_change_order() -> None:
    data = rows(3)
    data[1]["state"] = "removed"
    result = allocate_shares(data)
    assert [item["offer_id"] for item in result] == [1, 2, 3]
    assert [item["share"] for item in result] == [50, 0, 50]
