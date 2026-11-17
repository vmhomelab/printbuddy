"""Production cost estimate for a project ("Job").

Combines the job plan (grams per material + colour, print time per printer),
filament prices, the electricity price and the bill of materials into one
breakdown: what the job is expected to cost in total, what has already been
spent (actual archives + acquired BOM parts) and what is still to come.

Material price per kg, first match wins:
  1. inventory spools with the same material + colour that carry a price
     (several spools → average weighted by remaining filament)
  2. the filament catalogue entry for the material type
  3. the default filament price from the settings

Energy per printer hour, first match wins:
  1. the printer's configured average power (W)
  2. the printer's history: kWh / print hours of its archived prints
  3. the fleet average (history of all printers, else configured powers)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.archive import PrintArchive
from backend.app.models.filament import Filament
from backend.app.models.printer import Printer
from backend.app.models.project import Project
from backend.app.models.project_bom import ProjectBOMItem
from backend.app.models.spool import Spool
from backend.app.services.project_plan import PlanOverview, PlanProgress, load_plan, normalize_color, summarize_plan

DEFAULT_FILAMENT_COST = 25.0
DEFAULT_ENERGY_COST = 0.15


async def _float_setting(db: AsyncSession, key: str, default: float) -> float:
    from backend.app.api.routes.settings import get_setting

    value = await get_setting(db, key)
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


@dataclass
class EnergyRate:
    kwh_per_hour: float | None
    source: str  # power_setting | history | fleet_average | none
    detail: str | None = None
    prints: int = 0


@dataclass
class CostContext:
    """Prices and rates loaded once, shared by every project of a request."""

    currency: str
    default_cost_per_kg: float
    energy_cost_per_kwh: float
    spools: list[Spool]
    catalog: dict[str, float]  # material type (upper) → cost_per_kg
    printers: dict[int, Printer]
    printer_history: dict[int, tuple[float, float, int]]  # id → (kwh, hours, prints)
    fleet_rate: EnergyRate = field(default_factory=lambda: EnergyRate(None, "none"))

    def material_price(self, material: str, color: str) -> dict:
        mat = (material or "").strip().upper()
        hex_color = normalize_color(color)
        matching = [
            s
            for s in self.spools
            if s.cost_per_kg is not None
            and s.cost_per_kg > 0
            and (s.material or "").strip().upper() == mat
            and normalize_color((s.rgba or "")[:6]) == hex_color
        ]
        if matching:
            weights = [max(0.0, float(s.label_weight or 0) - float(s.weight_used or 0)) for s in matching]
            if sum(weights) > 0:
                price = sum(float(s.cost_per_kg or 0) * w for s, w in zip(matching, weights, strict=True)) / sum(
                    weights
                )
            else:
                price = sum(float(s.cost_per_kg or 0) for s in matching) / len(matching)
            return {
                "price_per_kg": round(price, 2),
                "source": "spools",
                "spools": [
                    {
                        "id": s.id,
                        "brand": s.brand,
                        "color_name": s.color_name,
                        "cost_per_kg": s.cost_per_kg,
                        "remaining_grams": round(w, 1),
                    }
                    for s, w in zip(matching, weights, strict=True)
                ],
            }
        if mat in self.catalog:
            return {"price_per_kg": round(self.catalog[mat], 2), "source": "catalog", "spools": []}
        return {"price_per_kg": round(self.default_cost_per_kg, 2), "source": "default", "spools": []}

    def printer_rate(self, printer_id: int) -> EnergyRate:
        printer = self.printers.get(printer_id)
        if printer is not None and printer.power_watts:
            return EnergyRate(printer.power_watts / 1000, "power_setting", f"{printer.power_watts:g} W")
        kwh, hours, prints = self.printer_history.get(printer_id, (0.0, 0.0, 0))
        if hours > 0 and kwh > 0:
            return EnergyRate(kwh / hours, "history", None, prints)
        return self.fleet_rate

    def model_rate(self, model: str) -> EnergyRate:
        rates = [
            self.printer_rate(p.id)
            for p in self.printers.values()
            if (p.model or "").upper() == model.upper() and p.is_active
        ]
        own = [r for r in rates if r.source in ("power_setting", "history") and r.kwh_per_hour]
        if own:
            return EnergyRate(
                sum(r.kwh_per_hour or 0.0 for r in own) / len(own),
                own[0].source if len({r.source for r in own}) == 1 else "history",
                None,
                sum(r.prints for r in own),
            )
        return self.fleet_rate


async def load_cost_context(db: AsyncSession) -> CostContext:
    from backend.app.api.routes.settings import get_setting

    currency = (await get_setting(db, "currency")) or "USD"
    default_cost = await _float_setting(db, "default_filament_cost", DEFAULT_FILAMENT_COST)
    energy_cost = await _float_setting(db, "energy_cost_per_kwh", DEFAULT_ENERGY_COST)

    spools = list((await db.execute(select(Spool).where(Spool.archived_at.is_(None)))).scalars().all())

    catalog: dict[str, float] = {}
    for f in (await db.execute(select(Filament))).scalars().all():
        key = (f.type or "").strip().upper()
        if key and f.cost_per_kg and key not in catalog:
            catalog[key] = float(f.cost_per_kg)

    printers = {p.id: p for p in (await db.execute(select(Printer))).scalars().all()}

    history_rows = await db.execute(
        select(
            PrintArchive.printer_id,
            func.sum(PrintArchive.energy_kwh),
            func.sum(PrintArchive.print_time_seconds),
            func.count(PrintArchive.id),
        )
        .where(
            PrintArchive.printer_id.is_not(None),
            PrintArchive.energy_kwh > 0,
            PrintArchive.print_time_seconds > 0,
            PrintArchive.status == "completed",
        )
        .group_by(PrintArchive.printer_id)
    )
    printer_history = {
        pid: (float(kwh or 0), float(secs or 0) / 3600, int(n or 0)) for pid, kwh, secs, n in history_rows.all()
    }

    ctx = CostContext(
        currency=currency,
        default_cost_per_kg=default_cost,
        energy_cost_per_kwh=energy_cost,
        spools=spools,
        catalog=catalog,
        printers=printers,
        printer_history=printer_history,
    )
    total_kwh = sum(v[0] for v in printer_history.values())
    total_hours = sum(v[1] for v in printer_history.values())
    if total_hours > 0 and total_kwh > 0:
        ctx.fleet_rate = EnergyRate(
            total_kwh / total_hours, "fleet_average", None, sum(v[2] for v in printer_history.values())
        )
    else:
        powers = [p.power_watts / 1000 for p in printers.values() if p.power_watts]
        if powers:
            ctx.fleet_rate = EnergyRate(sum(powers) / len(powers), "fleet_average", None, 0)
    return ctx


def _r(value: float) -> float:
    return round(value + 0.0, 2)


async def compute_project_costs(
    db: AsyncSession, project: Project, ctx: CostContext, overview: PlanOverview | None = None
) -> dict:
    if overview is None:
        overview = await load_plan(db, project.id)
    summary = summarize_plan(overview)
    has_plan = summary["total_plates"] > 0
    waste_pct = float(project.waste_percent or 0)
    waste_factor = waste_pct / 100

    # ---- Material (from the plan) -------------------------------------
    materials = []
    mat_planned = mat_done = mat_open = 0.0
    for m in summary["materials"]:
        price = ctx.material_price(m["type"], m["color"])
        per_g = price["price_per_kg"] / 1000
        row = {
            **m,
            **price,
            "planned_cost": _r(m["planned_grams"] * per_g),
            "completed_cost": _r(m["completed_grams"] * per_g),
            "remaining_cost": _r(m["remaining_grams"] * per_g),
        }
        mat_planned += m["planned_grams"] * per_g
        mat_done += m["completed_grams"] * per_g
        mat_open += m["remaining_grams"] * per_g
        materials.append(row)

    # ---- Energy (from the plan) ---------------------------------------
    groups: dict[str, dict] = {}
    for item in overview.items:
        if not item.est_print_time_seconds:
            continue
        prog = overview.progress.get(item.id) or PlanProgress(quantity=item.quantity)
        if item.printer_id and item.printer_id in ctx.printers:
            key = f"p:{item.printer_id}"
            label = ctx.printers[item.printer_id].name
            rate = ctx.printer_rate(item.printer_id)
            kind = "printer"
        elif item.target_model:
            key = f"m:{item.target_model.upper()}"
            label = item.target_model
            rate = ctx.model_rate(item.target_model)
            kind = "model"
        else:
            key = "unassigned"
            label = None
            rate = ctx.fleet_rate
            kind = "unassigned"
        hours = item.est_print_time_seconds / 3600
        group = groups.setdefault(
            key,
            {
                "key": key,
                "kind": kind,
                "label": label,
                "plates": 0,
                "planned_hours": 0.0,
                "remaining_hours": 0.0,
                "kwh_per_hour": round(rate.kwh_per_hour, 3) if rate.kwh_per_hour else None,
                "source": rate.source,
                "source_detail": rate.detail,
                "history_prints": rate.prints,
            },
        )
        group["plates"] += item.quantity
        group["planned_hours"] += hours * item.quantity
        group["remaining_hours"] += hours * prog.open_copies

    energy_rows = []
    en_planned = en_open = 0.0
    en_kwh = 0.0
    for g in groups.values():
        rate = g["kwh_per_hour"] or 0.0
        kwh = g["planned_hours"] * rate
        open_kwh = g["remaining_hours"] * rate
        g["planned_kwh"] = round(kwh, 3)
        g["planned_cost"] = _r(kwh * ctx.energy_cost_per_kwh)
        g["remaining_cost"] = _r(open_kwh * ctx.energy_cost_per_kwh)
        g["planned_hours"] = round(g["planned_hours"], 2)
        g["remaining_hours"] = round(g["remaining_hours"], 2)
        en_planned += kwh * ctx.energy_cost_per_kwh
        en_open += open_kwh * ctx.energy_cost_per_kwh
        en_kwh += kwh
        energy_rows.append(g)

    # ---- BOM -----------------------------------------------------------
    bom_rows = []
    bom_total = bom_acquired = 0.0
    bom_items = (
        (
            await db.execute(
                select(ProjectBOMItem)
                .where(ProjectBOMItem.project_id == project.id)
                .order_by(ProjectBOMItem.sort_order, ProjectBOMItem.id)
            )
        )
        .scalars()
        .all()
    )
    for b in bom_items:
        if not b.unit_price:
            continue
        acquired = min(b.quantity_acquired or 0, b.quantity_needed or 0)
        cost = b.unit_price * (b.quantity_needed or 0)
        bom_total += cost
        bom_acquired += b.unit_price * acquired
        bom_rows.append(
            {
                "id": b.id,
                "name": b.name,
                "quantity_needed": b.quantity_needed,
                "quantity_acquired": b.quantity_acquired,
                "unit_price": b.unit_price,
                "cost": _r(cost),
            }
        )
    bom_without_price = sum(1 for b in bom_items if not b.unit_price)

    # ---- Actual spend (archives) ---------------------------------------
    actual = (
        await db.execute(
            select(
                func.coalesce(func.sum(PrintArchive.cost), 0),
                func.coalesce(func.sum(PrintArchive.energy_cost), 0),
                func.coalesce(func.sum(PrintArchive.energy_kwh), 0),
                func.count(PrintArchive.id),
            ).where(PrintArchive.project_id == project.id)
        )
    ).one()
    actual_material, actual_energy, actual_kwh, actual_prints = (
        float(actual[0]),
        float(actual[1]),
        float(actual[2]),
        int(actual[3]),
    )

    def totals(material: float, energy: float, bom: float) -> dict:
        return {
            "material": _r(material),
            "energy": _r(energy),
            "bom": _r(bom),
            "total": _r(material + energy + bom),
        }

    if has_plan:
        planned = totals(mat_planned * (1 + waste_factor), en_planned, bom_total)
        remaining = totals(mat_open * (1 + waste_factor), en_open, bom_total - bom_acquired)
    else:
        # Without a plan the best estimate is what has been spent so far
        planned = totals(actual_material, actual_energy, bom_total)
        remaining = totals(0, 0, bom_total - bom_acquired)
    incurred = totals(actual_material, actual_energy, bom_acquired)

    warnings = []
    if summary["unestimated_items"]:
        warnings.append({"code": "unestimated_plates", "count": summary["unestimated_items"]})
    for m in materials:
        if m["source"] == "default":
            warnings.append(
                {"code": "default_price", "type": m["type"], "color": m["color"], "color_name": m.get("color_name")}
            )
    if any(g["source"] == "none" for g in energy_rows):
        warnings.append({"code": "no_energy_rate"})
    if bom_without_price:
        warnings.append({"code": "bom_without_price", "count": bom_without_price})

    return {
        "currency": ctx.currency,
        "has_plan": has_plan,
        "energy_cost_per_kwh": ctx.energy_cost_per_kwh,
        "waste_percent": waste_pct,
        "budget": project.budget,
        "total_plates": summary["total_plates"],
        "completed_plates": summary["completed_plates"],
        "planned": planned,
        "incurred": incurred,
        "remaining": remaining,
        "material": {
            "rows": materials,
            "planned_grams": summary["planned_filament_grams"],
            "planned_cost": _r(mat_planned),
            "waste_cost": _r(mat_planned * waste_factor),
            "total_cost": _r(mat_planned * (1 + waste_factor)),
        },
        "energy": {"rows": energy_rows, "planned_kwh": round(en_kwh, 3), "planned_cost": _r(en_planned)},
        "bom": {"rows": bom_rows, "total": _r(bom_total), "acquired": _r(bom_acquired)},
        "actual": {
            "material": _r(actual_material),
            "energy": _r(actual_energy),
            "energy_kwh": round(actual_kwh, 3),
            "prints": actual_prints,
        },
        "warnings": warnings,
    }
