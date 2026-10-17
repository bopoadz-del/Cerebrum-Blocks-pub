"""Settings a block is GIVEN, never settings a block goes looking for.

KERNEL_DEFAULTS 1.5.

THE RULE
--------
Block code does not call ``os.getenv``. It reads what it was handed.

This is not tidiness. A block that reaches into the environment cannot be
constructed twice with different settings, cannot be tested against a second
configuration without mutating the process, and -- the expensive one -- gives
no answer to "what does this block need in order to run?" other than reading
its source. That question is what a generated zip has to answer on a stranger's
laptop before it boots.

There are 31 block modules in ``app/blocks/`` making 85 such calls today. This
PR does not change them; it lands the pattern and applies it to one block. The
rest are ordered in the L2.6 migration plan.

THE FALLBACK LADDER
-------------------
Every external dependency has a local fallback, so a zip boots on a laptop
with zero services running:

===================  =====================  =================================
dependency           preferred              fallback
===================  =====================  =================================
cache                Redis                  in-process dict
relational store     PostgreSQL             SQLite file
object store         S3-compatible bucket   local directory
language model       provider API           stub returning ``refused``
===================  =====================  =================================

The LLM rung is the one that matters most and is the easiest to get wrong.
The fallback is NOT a canned answer or a smaller model -- it is a stub that
returns :data:`~app.core.block_result.REFUSED` with a reason saying no model
was configured. A fallback that answers anyway converts "this platform has no
LLM" into "this platform is confidently wrong", which is the failure class
the whole contract exists to prevent.

DEGRADING IS NOT THE SAME AS PRETENDING
---------------------------------------
A block on a fallback rung must say so. :meth:`Config.backend` returns the
rung that was actually taken so the block can report it, and
:func:`fallback_note` turns that into a line a reader can act on. Silently
serving from an in-process dict while the caller believes it is talking to
Redis is how a cache "works" in testing and loses every write in production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Tuple

#: The single sanctioned place a process reads the environment for block
#: settings. Anything else is the thing this module exists to stop.
_ENV_IS_READ_HERE_AND_NOWHERE_ELSE = True


class MissingSetting(KeyError):
    """A block asked for a setting nobody gave it."""


class Config:
    """An immutable-ish view of the settings a block was handed.

    Wraps a plain mapping, so a block that already receives ``config`` as a
    dict loses nothing by adopting this. Lookup walks to ``parent`` when a key
    is absent, which is how a per-block override sits on top of a
    platform-wide default without either one having to know about the other.
    """

    __slots__ = ("_values", "_parent", "_source")

    def __init__(
        self,
        values: Optional[Mapping[str, Any]] = None,
        *,
        parent: Optional["Config"] = None,
        source: str = "given",
    ) -> None:
        self._values: Dict[str, Any] = dict(values or {})
        self._parent = parent
        self._source = source

    # -- construction ------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        *,
        keys: Optional[Iterable[str]] = None,
        parent: Optional["Config"] = None,
    ) -> "Config":
        """Build a Config from the environment. **The only sanctioned read.**

        Call this once, where the platform is assembled, and hand the result
        down. ``env`` is a parameter so a test never has to mutate
        ``os.environ`` to try a second configuration.

        ``keys`` restricts what is lifted; without it, everything is taken.
        Naming the keys is preferred -- it makes a block's dependencies a
        list somebody can read rather than "whatever happened to be set".
        """
        environ = os.environ if env is None else env
        if keys is None:
            values = dict(environ)
        else:
            values = {key: environ[key] for key in keys if key in environ}
        return cls(values, parent=parent, source="env")

    def child(self, values: Optional[Mapping[str, Any]] = None, **overrides: Any) -> "Config":
        """A Config that overrides this one and falls back to it."""
        merged = dict(values or {})
        merged.update(overrides)
        return Config(merged, parent=self, source="override")

    # -- reading -----------------------------------------------------------

    def get(self, name: str, default: Any = None) -> Any:
        if name in self._values:
            return self._values[name]
        if self._parent is not None:
            return self._parent.get(name, default)
        return default

    def require(self, name: str) -> Any:
        """Read a setting that has no sensible default.

        Raises with the setting's name in the message, because "KeyError:
        'x'" three frames deep in a pipeline tells a reader nothing about
        which block needed what.
        """
        sentinel = object()
        value = self.get(name, sentinel)
        if value is sentinel:
            raise MissingSetting(
                "no value was given for %r; block code must be handed its "
                "settings rather than reading the environment" % name
            )
        return value

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        if name in self._values:
            return True
        return self._parent is not None and name in self._parent

    def __getitem__(self, name: str) -> Any:
        return self.require(name)

    def __iter__(self) -> Iterator[str]:
        seen = set(self._values)
        for key in self._values:
            yield key
        if self._parent is not None:
            for key in self._parent:
                if key not in seen:
                    yield key

    def as_dict(self) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        if self._parent is not None:
            merged.update(self._parent.as_dict())
        merged.update(self._values)
        return merged

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Config(%d key(s), source=%r%s)" % (
            len(self._values),
            self._source,
            ", parent=yes" if self._parent is not None else "",
        )

    # -- the ladder --------------------------------------------------------

    def backend(self, dependency: str, default: Optional[str] = None) -> Optional[str]:
        """Which rung this block was told to use, e.g. ``cache_backend``.

        ``None`` means "not pinned, resolve it yourself". Returning the rung
        rather than a boolean is deliberate: a block that can only answer
        "have I got Redis, yes or no" cannot tell a reader which of three
        fallbacks it landed on.
        """
        return self.get("%s_backend" % dependency, default)


@dataclass(frozen=True)
class Rung:
    """One rung of the fallback ladder."""

    dependency: str
    preferred: str
    fallback: str
    note: str


#: The documented ladder. Consumed by the migration plan and by tests that
#: assert a block's fallback is the one the platform promises, rather than
#: whatever its author reached for.
FALLBACK_LADDER: Tuple[Rung, ...] = (
    Rung(
        "cache",
        "redis",
        "memory",
        "an in-process dict. Lost on restart and not shared between workers, "
        "which the block must say rather than imply.",
    ),
    Rung(
        "database",
        "postgres",
        "sqlite",
        "a local file. Fine for a single-process zip; not for concurrent "
        "writers.",
    ),
    Rung(
        "objects",
        "s3",
        "file",
        "a local directory. Nothing is replicated and nothing is durable "
        "beyond the disk it sits on.",
    ),
    Rung(
        "llm",
        "provider",
        "refuse",
        "a stub that returns refused. NOT a canned answer and NOT a smaller "
        "model: a fallback that answers anyway turns 'this platform has no "
        "LLM' into 'this platform is confidently wrong'.",
    ),
)

LADDER_BY_DEPENDENCY: Dict[str, Rung] = {rung.dependency: rung for rung in FALLBACK_LADDER}


def fallback_note(dependency: str, rung: str) -> str:
    """A line a reader can act on when a block degraded.

    Used in a ``BlockResult`` reason or note. Degrading is legitimate;
    degrading quietly is not.
    """
    known = LADDER_BY_DEPENDENCY.get(dependency)
    if known is None:
        return "%s is running on %r" % (dependency, rung)
    if rung == known.preferred:
        return "%s: %s" % (dependency, known.preferred)
    return "%s fell back to %r (preferred: %r) -- %s" % (
        dependency,
        rung,
        known.preferred,
        known.note,
    )
