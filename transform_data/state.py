"""One user's work, in memory only: the uploaded tables, the step list and its result.

    store = registry.for_request(request, create=True)[0]
    store.add_upload(...)          # data_core loads the file, the rows become a pandas table
    store.add_step(step)           # checked, run, kept only if it works
    store.result                   # every table after all steps: what the user downloads

Uploaded tables are kept as they came in; the result is always worked out again from them,
so "undo the last step" is exact.
"""

import logging

from data_core.frames import dataset_frame
from data_core.loading import load_file
from data_core.store import MB, DataStore, StoreRegistry

from .engine.exceptions import TransformError
from .engine.pipeline import (
    StepOutcome,
    TransformStep,
    append_step,
    apply_steps_with_report,
    input_names,
    remove_last_step,
    replace_last_step,
    validate_step,
)
from .engine.workspace import NamedFrame, name_key, suggest_frame_name

logger = logging.getLogger(__name__)

SESSION_KEY = "transform_data_store"


class StepRefused(Exception):
    """The step can't be added. The message is shown to the user as it is."""


class TransformStore(DataStore):
    def __init__(self, memory_mb: int | None = None):
        super().__init__(memory_mb)
        self.uploads: dict[str, NamedFrame] = {}  # name → table, in upload order
        self.steps: list[TransformStep] = []
        self.result: dict[str, NamedFrame] = {}  # every table after all steps
        self.outcomes: list[StepOutcome] = []

    # ---------- tables ----------

    def add_upload(self, file_name: str, data) -> list[str]:
        """Load a CSV / Excel / JSON file (one table per sheet or JSON list). Returns the new
        table names. Raises data_core.loading.UploadRejected with a plain message."""
        with self.lock:
            datasets = load_file(self, file_name, data)
            names = []
            for dataset in datasets:
                frame = dataset_frame(self, dataset)
                taken = [*self.uploads, *self.result]
                name = suggest_frame_name(dataset.name, taken)
                # "sales.xlsx - Jan": the label the recipe code reads file and sheet from.
                label = dataset.source_file.replace(" › ", " - ")
                self.uploads[name] = NamedFrame(
                    name=name, frame=frame, origin="upload", source_label=label
                )
                names.append(name)
                # The rows now live in pandas; DuckDB was only needed to read the file.
                self.remove_dataset(dataset.dataset_id)
            self._run()
            return names

    def remove_upload(self, name: str) -> None:
        """Remove an uploaded table. Refused while a step reads it."""
        with self.lock:
            key = name_key(name)
            for number, step in enumerate(self.steps, start=1):
                if key in {name_key(used) for used in input_names(step)}:
                    logger.info("Remove refused: step %s uses %s", number, name)
                    raise StepRefused(
                        f"Step {number} uses “{name}”. Undo the steps that use it first."
                    )
            self.uploads = {held: t for held, t in self.uploads.items() if name_key(held) != key}
            self._run()

    def table(self, name: str) -> NamedFrame | None:
        key = name_key(name)
        return next((t for held, t in self.result.items() if name_key(held) == key), None)

    # ---------- steps ----------

    def add_step(self, step: TransformStep) -> StepOutcome:
        """Check and run a new last step. Kept only if it runs; else StepRefused."""
        with self.lock:
            failed = self.failed
            if failed is not None:  # e.g. a recipe step that can't run on these tables
                message = (
                    f"Step {failed.index + 1} can't run ({failed.message}). "
                    "Undo the steps from there, or upload the missing table, then add new steps."
                )
                logger.info("Step refused, an earlier step fails: %s", failed.message)
                raise StepRefused(message)
            return self._try_steps(append_step(self.steps, step), base=self.result, step=step)

    def replace_last(
        self, step: TransformStep, before_last: dict[str, NamedFrame] | None = None
    ) -> StepOutcome:
        """Swap the last step. `before_last` = tables_before_last(), if the caller has it."""
        with self.lock:
            if before_last is None:
                before_last = self._result_of(self.steps[:-1])
            return self._try_steps(replace_last_step(self.steps, step), base=before_last, step=step)

    def undo_last(self) -> None:
        with self.lock:
            self.steps = remove_last_step(self.steps)
            self._run()

    def load_steps(self, steps: list[TransformStep]) -> list[StepOutcome]:
        """Use a recipe's steps on the tables loaded now. Steps that can't run are kept, and
        the outcomes say which one stopped and why."""
        with self.lock:
            self.steps = list(steps)
            self._run()
            return self.outcomes

    def clear_steps(self) -> None:
        with self.lock:
            self.steps = []
            self._run()

    def tables_before_last(self) -> dict[str, NamedFrame]:
        """The tables as they were before the last step (what "Edit last step" works on)."""
        with self.lock:
            return self._result_of(self.steps[:-1])

    @property
    def failed(self) -> StepOutcome | None:
        """The step that stopped the run, if one did (only after loading a recipe)."""
        return next((outcome for outcome in self.outcomes if not outcome.ok), None)

    # ---------- internals ----------

    def _result_of(self, steps: list[TransformStep]) -> dict[str, NamedFrame]:
        result, _ = apply_steps_with_report(self.uploads, steps)
        return result

    def _try_steps(
        self, steps: list[TransformStep], base: dict[str, NamedFrame], step: TransformStep
    ) -> StepOutcome:
        try:
            validate_step(step, base)
        except TransformError as error:
            logger.info("Step refused: %s", error)
            raise StepRefused(str(error)) from error
        result, outcomes = apply_steps_with_report(self.uploads, steps)
        last = outcomes[-1] if outcomes else None
        if last is None or not last.ok or len(outcomes) < len(steps):
            message = last.message if last else "The step could not run."
            logger.info("Step failed on the data: %s", message)
            raise StepRefused(message)
        needed = self._frames_bytes(result)
        if needed > self.memory_limit_bytes:
            logger.warning(
                "Step refused: needs %s MB, limit %s MB",
                needed // MB,
                self.memory_limit_bytes // MB,
            )
            raise StepRefused(
                f"This step would need about {needed // MB:,} MB, more than the "
                f"{self.memory_limit_bytes // MB:,} MB allowed per user. Filter rows or remove "
                "columns first (a join on a repeated value can multiply rows)."
            )
        self.steps, self.result, self.outcomes = steps, result, outcomes
        self.refresh_memory()
        return last

    def _run(self) -> None:
        self.result, self.outcomes = apply_steps_with_report(self.uploads, self.steps)
        self.refresh_memory()

    def refresh_memory(self) -> None:
        """DuckDB's memory plus the pandas tables held for this user."""
        super().refresh_memory()
        self.memory_used_bytes += self._frames_bytes(self.result)

    def _frames_bytes(self, result: dict[str, NamedFrame]) -> int:
        """Memory of the uploaded tables plus `result`'s tables (each table counted once)."""
        frames = {id(t.frame): t.frame for t in [*self.uploads.values(), *result.values()]}
        return sum(int(frame.memory_usage(deep=True).sum()) for frame in frames.values())

    def close(self) -> None:
        with self.lock:
            self.uploads, self.result, self.steps, self.outcomes = {}, {}, [], []
        super().close()


registry = StoreRegistry(TransformStore, SESSION_KEY)
