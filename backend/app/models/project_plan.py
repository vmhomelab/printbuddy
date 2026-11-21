from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class ProjectPlanItem(Base):
    """One planned plate of a project ("Job").

    A job is a project whose plan lists every plate that has to be printed:
    which library file / plate, how many copies, which material + colour per
    filament slot and (optionally) which printer or printer model should run
    it. Queue items and archives created from a plan item carry its id
    (``plan_item_id``) so the job can track printed / queued / remaining
    copies per plate.
    """

    __tablename__ = "project_plan_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)

    # Source file. SET NULL keeps the plan row (and its history) when the
    # library file is deleted; the UI then flags the row as "file missing".
    library_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_files.id", ondelete="SET NULL"), nullable=True
    )
    # 1-indexed plate of a multi-plate 3MF (None = plate 1 / single plate)
    plate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Display name (defaults to plate / file name) and optional group such as
    # "Base set" or "Accessory A" so the plan can be organised in sections.
    name: Mapped[str] = mapped_column(String(255))
    group_label: Mapped[str | None] = mapped_column(String(100), nullable=True)

    quantity: Mapped[int] = mapped_column(Integer, default=1)

    # Effective filaments per slot:
    # [{"slot_id": 1, "type": "PETG", "color": "#000000", "color_name": "Black",
    #   "used_grams": 12.3, "original_type": "PLA", "original_color": "#FFFFFF"}]
    # ``original_*`` is what the 3MF was sliced with; a differing type/colour
    # becomes a filament override on the queue items.
    filaments: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Estimates for ONE copy of this plate (from slice metadata, or entered
    # manually for unsliced files).
    est_print_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    est_filament_grams: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Assignment: a specific printer OR a printer model (any idle printer of
    # that model). Both empty = unassigned queue item.
    printer_id: Mapped[int | None] = mapped_column(ForeignKey("printers.id", ondelete="SET NULL"), nullable=True)
    target_model: Mapped[str | None] = mapped_column(String(50), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    project: Mapped["Project"] = relationship(back_populates="plan_items")
    library_file: Mapped["LibraryFile | None"] = relationship()
    printer: Mapped["Printer | None"] = relationship()


from backend.app.models.library import LibraryFile  # noqa: E402
from backend.app.models.printer import Printer  # noqa: E402
from backend.app.models.project import Project  # noqa: E402
