from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class PrinterFleetGroup(Base):
    """Operational printer grouping for farm command center workflows."""

    __tablename__ = "printer_fleet_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    members: Mapped[list["PrinterFleetGroupMember"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class PrinterFleetGroupMember(Base):
    """Membership link between a printer and an operational fleet group."""

    __tablename__ = "printer_fleet_group_members"
    __table_args__ = (UniqueConstraint("group_id", "printer_id", name="uq_printer_fleet_group_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("printer_fleet_groups.id", ondelete="CASCADE"), index=True)
    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    group: Mapped[PrinterFleetGroup] = relationship(back_populates="members")
