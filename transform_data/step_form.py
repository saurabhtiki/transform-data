"""The "add a step" form: drawn from the operation's ParamSpecs, read back into a step.

The form posts plain names:
    in_<role>      the table(s) for an input role (a list for a multi role like Append)
    p_<param>      a parameter (a list for COLUMNS / CHOICES; a checkbox for BOOLEAN)
    output_mode    in_place | new
    output_name    the new table's name
"""

from dataclasses import dataclass, field

from .engine.params import (
    ParamKind,
    ParamSpec,
    collect_params,
    default_value,
    option_columns,
    visible_params,
)
from .engine.pipeline import TransformStep, make_step, suggested_output_name
from .engine.registry import CATEGORY_ORDER, OperationSpec, get_operation, operations_by_category
from .engine.workspace import NamedFrame, name_key

LIST_KINDS = {ParamKind.COLUMNS, ParamKind.CHOICES}
NUMBER_KINDS = {ParamKind.INTEGER, ParamKind.NUMBER}


@dataclass
class FieldView:
    """One box on the form, ready for the template."""

    spec: ParamSpec
    value: object
    options: list[str] = field(default_factory=list)
    refresh: bool = False  # changing it redraws the form (other boxes depend on it)

    @property
    def input_name(self) -> str:
        return f"p_{self.spec.name}"

    @property
    def kind(self) -> str:
        return str(self.spec.kind)

    @property
    def selected(self) -> list[str]:
        if isinstance(self.value, list):
            return [str(item) for item in self.value]
        return [] if self.value in (None, "") else [str(self.value)]


@dataclass
class RoleView:
    name: str
    label: str
    help: str
    multi: bool
    selected: list[str]


@dataclass
class StepForm:
    spec: OperationSpec
    roles: list[RoleView]
    fields: list[FieldView]
    table_names: list[str]
    output_mode: str
    output_name: str
    columns: list[str]  # the first input's columns (for the formula chips)
    editing: bool = False


def picker_groups() -> list[tuple[str, list[OperationSpec]]]:
    """Operations grouped for the picker, in the picker's category order."""
    grouped = operations_by_category()
    return [(category, grouped[category]) for category in CATEGORY_ORDER if grouped.get(category)]


def _find(tables: dict[str, NamedFrame], name: str) -> NamedFrame | None:
    key = name_key(name)
    return next((t for held, t in tables.items() if name_key(held) == key), None)


def read_raw(spec: OperationSpec, data) -> tuple[dict, dict]:
    """(inputs, raw param values) from the posted form (a QueryDict)."""
    inputs: dict = {}
    for role in spec.inputs:
        key = f"in_{role.name}"
        inputs[role.name] = data.getlist(key) if role.multi else data.get(key, "")
    raw: dict = {}
    for param in spec.params:
        key = f"p_{param.name}"
        if param.kind in LIST_KINDS:
            raw[param.name] = [value for value in data.getlist(key) if value]
        elif param.kind is ParamKind.BOOLEAN:
            raw[param.name] = data.get(key) == "on"
        else:
            value = data.get(key)
            # An empty optional number box means "not set", not "0".
            raw[param.name] = None if param.kind in NUMBER_KINDS and value in ("", None) else value
    return inputs, raw


def build_form(
    operation: str,
    tables: dict[str, NamedFrame],
    *,
    data=None,
    existing: TransformStep | None = None,
    preferred_table: str = "",
) -> StepForm:
    """The form for an operation. `data` = what the user has filled in so far (a redraw),
    `existing` = the step being edited, else defaults."""
    spec = get_operation(operation)
    names = list(tables)
    if data is not None:
        inputs, raw = read_raw(spec, data)
        output_mode = data.get("output_mode") or spec.default_output
        output_name = data.get("output_name", "")
    elif existing is not None:
        inputs = dict(existing.get("inputs", {}))
        raw = {p.name: default_value(p, existing.get("params", {})) for p in spec.params}
        output_mode = existing["output"]["mode"]
        output_name = existing["output"]["name"]
    else:
        first = preferred_table if _find(tables, preferred_table) else (names[0] if names else "")
        inputs = {}
        for index, role in enumerate(spec.inputs):
            if role.multi:
                inputs[role.name] = names[:2]
            else:  # e.g. Join: left = the table on screen, right = the next one
                others = [name for name in names if name != first]
                inputs[role.name] = first if index == 0 else (others[0] if others else first)
        raw = {p.name: default_value(p) for p in spec.params}
        output_mode, output_name = spec.default_output, ""

    columns_by_role: dict[str, list[str]] = {}
    for role in spec.inputs:
        chosen = inputs.get(role.name)
        chosen_list = chosen if isinstance(chosen, list) else [chosen]
        merged: list[str] = []
        for name in chosen_list:
            held = _find(tables, str(name or ""))
            if held is not None:
                merged += [str(c) for c in held.frame.columns if str(c) not in merged]
        columns_by_role[role.name] = merged

    refreshers = {p.depends_on for p in spec.params if p.depends_on}
    fields = [
        FieldView(
            spec=param,
            value=raw.get(param.name),
            options=option_columns(param, columns_by_role) or list(param.choices),
            refresh=param.name in refreshers,
        )
        for param in visible_params(spec.params, raw)
    ]
    roles = [
        RoleView(
            role.name,
            role.label,
            role.help,
            role.multi,
            [str(v) for v in inputs.get(role.name)]
            if role.multi
            else [str(inputs.get(role.name) or "")],
        )
        for role in spec.inputs
    ]
    if output_mode == "new" and not output_name:
        output_name = suggested_output_name(spec, inputs, tables)
    first_role = spec.inputs[0].name if spec.inputs else "source"
    return StepForm(
        spec=spec,
        roles=roles,
        fields=fields,
        table_names=names,
        output_mode=output_mode,
        output_name=output_name,
        columns=columns_by_role.get(first_role, []),
        editing=existing is not None,
    )


def read_step(operation: str, data, tables: dict[str, NamedFrame]) -> TransformStep:
    """The step the posted form describes. Raises the engine's TransformError subclasses
    (InvalidStepParamsError …) with a message for the user."""
    spec = get_operation(operation)
    inputs, raw = read_raw(spec, data)
    params = collect_params(spec.params, raw)
    output_mode = data.get("output_mode") or spec.default_output
    if output_mode == "new":
        output_name = data.get("output_name", "").strip()
    else:  # in place: the answer replaces the first input table
        first = inputs.get(spec.primary_role)
        output_name = (first[0] if isinstance(first, list) and first else first) or ""
    return make_step(operation, inputs, params, output_mode, str(output_name))
