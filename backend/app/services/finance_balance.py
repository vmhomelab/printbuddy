"""Canonical definition and synchronization of a user's personal balance."""

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.finance import CostCenter, UserWallet, WalletTransaction


def transaction_affects_personal_balance(
    user_id: int,
    cost_center_id: int | None,
    *,
    is_private: bool = False,
    owner_user_id: int | None = None,
) -> bool:
    """Apply the canonical definition to already-loaded transaction data."""

    return cost_center_id is None or (is_private and owner_user_id == user_id)


def personal_balance_condition(user_id: int):
    """Return the SQL condition for transactions in a personal wallet.

    Unassigned transactions and transactions assigned to the user's own
    private cost center are personal. Shared cost centers are not.
    """

    return or_(
        WalletTransaction.cost_center_id.is_(None),
        and_(CostCenter.is_private.is_(True), CostCenter.owner_user_id == user_id),
    )


async def calculate_personal_balance(db: AsyncSession, user_id: int) -> float:
    result = await db.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0.0))
        .select_from(WalletTransaction)
        .outerjoin(CostCenter, WalletTransaction.cost_center_id == CostCenter.id)
        .where(
            WalletTransaction.user_id == user_id,
            WalletTransaction.is_voided.is_(False),
            personal_balance_condition(user_id),
        )
    )
    return round(float(result.scalar_one() or 0.0), 2)


async def is_personal_transaction(db: AsyncSession, user_id: int, cost_center_id: int | None) -> bool:
    if cost_center_id is None:
        return True
    result = await db.execute(
        select(CostCenter.is_private, CostCenter.owner_user_id).where(CostCenter.id == cost_center_id)
    )
    center = result.one_or_none()
    if center is None:
        return False
    return transaction_affects_personal_balance(
        user_id,
        cost_center_id,
        is_private=bool(center.is_private),
        owner_user_id=center.owner_user_id,
    )


async def sync_personal_wallet_balance(db: AsyncSession, wallet: UserWallet) -> float:
    balance = await calculate_personal_balance(db, wallet.user_id)
    wallet.balance = balance
    db.add(wallet)
    return balance
