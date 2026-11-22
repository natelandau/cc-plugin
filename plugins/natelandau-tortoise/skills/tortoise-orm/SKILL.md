---
name: tortoise-orm
description: "Use when writing or modifying code that uses Tortoise ORM v1.x: Model definitions, fields, relations (ForeignKeyField, ManyToManyField, OneToOneField), queries, prefetch_related/select_related, transactions, signals, validators, migrations, tests, Tortoise.init, RegisterTortoise, or tortoise.contrib.pydantic. Also when the user mentions tortoise-orm or an async ORM on asyncpg/asyncmy, even without saying 'Tortoise'."
---

# Tortoise ORM v1.x

Async Python ORM. Backends: PostgreSQL (asyncpg/psycopg), MySQL (asyncmy/aiomysql), SQLite, MSSQL.

## Critical rules

1. Await every QuerySet. QuerySets are lazy; `Model.filter(...)` without `await` silently returns a QuerySet object, not results.
2. Fetch a relation before reading it. An unfetched relation raises `NoValuesFetched`; there is no lazy loading. Use `await obj.fetch_related("field")` or `select_related`/`prefetch_related` on the QuerySet.
3. `generate_schemas()` is for development only. Use migrations in production.
4. No transactions inside `asyncio.gather()` or other concurrent tasks. Transactions are stateful and sequential; concurrent use corrupts data.
5. Use `Tortoise.get_connection()`, not `from tortoise import connections` (deprecated in v1.0+).
6. Save both objects before M2M `.add()`.
7. `auto_now`/`auto_now_add` are Python-side only and create no DB DEFAULT. When the database must set the value (raw SQL inserts, migrations), use `db_default=Now()`.
8. Call `Tortoise.init_models()` before creating Pydantic models when full ORM init has not run; otherwise relations do not resolve.

```python
# WRONG: silently returns a QuerySet object, not a list
users = Model.filter(active=True)
# CORRECT
users = await Model.filter(active=True)

# WRONG: raises NoValuesFetched
event = await Event.get(id=1)
print(event.tournament.name)
# CORRECT
event = await Event.get(id=1)
await event.fetch_related("tournament")
print(event.tournament.name)
# ALSO CORRECT: via QuerySet
event = await Event.all().select_related("tournament").get(id=1)
```

## Initialization

```python
from tortoise import Tortoise

await Tortoise.init(
    db_url="sqlite://db.sqlite3",
    modules={"models": ["app.models"]},
)
await Tortoise.generate_schemas()  # DEV ONLY -- use migrations in production
```

Multi-database config: a dict with `connections` and `apps` keys. Full structure: `references/api-reference.md`.

FastAPI (v1.x lifespan pattern):

```python
from contextlib import asynccontextmanager
from tortoise.contrib.fastapi import RegisterTortoise

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with RegisterTortoise(
        app, db_url="sqlite://db.sqlite3",
        modules={"models": ["app.models"]},
        generate_schemas=True,
    ):
        yield

app = FastAPI(lifespan=lifespan)
```

Connection access (v1.0+):

```python
conn = Tortoise.get_connection("default")
await Tortoise.close_connections()
```

## Defining Models

```python
from tortoise.models import Model
from tortoise import fields

class Tournament(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    created = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "tournaments"
        ordering = ["name"]
```

No primary key defined: an auto-incrementing `IntField` named `id` is created. `.pk` aliases any PK.

Meta options: `table`, `schema`, `abstract`, `unique_together`, `indexes`, `ordering`, `table_description`, `fetch_db_defaults`, `manager`.

Inheritance via abstract base classes or mixins:

```python
class TimestampMixin:
    created_at = fields.DatetimeField(null=True, auto_now_add=True)
    modified_at = fields.DatetimeField(null=True, auto_now=True)

class AbstractBase(Model):
    class Meta:
        abstract = True

class User(TimestampMixin, AbstractBase):
    name = fields.CharField(max_length=100)
```

### Fields

Common parameters: `null`, `default` (supports callables), `unique`, `db_index`, `source_field` (custom DB column name), `description`, `validators`, `generated`, `primary_key`.

| Category | Fields                                                                                                            |
| -------- | ----------------------------------------------------------------------------------------------------------------- |
| Numeric  | `IntField`, `BigIntField`, `SmallIntField`, `FloatField`, `DecimalField(max_digits, decimal_places)`              |
| Text     | `CharField(max_length)`, `TextField`, `BinaryField`                                                               |
| Temporal | `DateField`, `DatetimeField(auto_now, auto_now_add)`, `TimeField`, `TimeDeltaField`                               |
| Other    | `BooleanField`, `UUIDField`, `JSONField(encoder, decoder)`, `CharEnumField(enum_type)`, `IntEnumField(enum_type)` |

Database-level defaults (see rule 7):

```python
from tortoise.fields.db_defaults import Now, SqlDefault
fields.DatetimeField(db_default=Now())
fields.IntField(db_default=SqlDefault("0"))
```

### Relations

ForeignKey:

```python
class Event(Model):
    tournament: fields.ForeignKeyRelation[Tournament] = fields.ForeignKeyField(
        "models.Tournament", related_name="events", on_delete=fields.OnDelete.CASCADE
    )
```

- DB column is `tournament_id`. Read it directly when the related object is not needed.
- `on_delete`: `CASCADE`, `RESTRICT`, `SET_NULL` (requires `null=True`), `SET_DEFAULT`, `NO_ACTION`.

ManyToMany:

```python
participants: fields.ManyToManyRelation["Team"] = fields.ManyToManyField(
    "models.Team", related_name="events", through="event_team"
)
```

OneToOne:

```python
address: fields.OneToOneRelation[Address] = fields.OneToOneField(
    "models.Address", on_delete=fields.OnDelete.CASCADE, related_name="event"
)
```

Annotate reverse relations for type hints:

```python
class Tournament(Model):
    events: fields.ReverseRelation["Event"]
```

## Querying

```python
# Create
obj = await Model.create(name="foo")
obj = Model(name="foo"); await obj.save()

# Read
obj = await Model.get(id=1)              # raises DoesNotExist / MultipleObjectsReturned
obj = await Model.get_or_none(id=1)       # returns None if not found
items = await Model.filter(name="foo")    # list
items = await Model.all()

# Update
await Model.filter(id=1).update(name="bar")  # bulk, returns count
obj.name = "bar"; await obj.save()            # instance

# Delete
await Model.filter(id=1).delete()
await obj.delete()

# Upsert
obj, created = await Model.get_or_create(name="x", defaults={"field": "val"})
obj, created = await Model.update_or_create(name="x", defaults={"field": "val"})
```

QuerySet methods: `filter`, `exclude`, `all`, `first`, `last`, `count`, `exists`, `values`, `values_list`, `only`, `defer`, `order_by`, `limit`, `offset`, `distinct`, `group_by`, `annotate`, `select_related`, `prefetch_related`, `select_for_update`, `using_db`, `raw`, `explain`.

Filter operators (double-underscore): `__gt`, `__gte`, `__lt`, `__lte`, `__in`, `__not_in`, `__not`, `__isnull`, `__contains`, `__icontains`, `__startswith`, `__istartswith`, `__endswith`, `__iendswith`, `__iexact`, `__search`, `__range`, `__year`, `__month`, `__day`, and more.

Q objects, F expressions, aggregation, bulk:

```python
from tortoise.expressions import Q, F
from tortoise.functions import Count, Sum, Avg, Max, Min

await Event.filter(Q(id__in=[1, 2]) | Q(name="3"))
await Event.filter(Q(name="x") & ~Q(tournament__name="y"))

await Model.filter(field_a__gt=F("field_b"))
await Model.filter(id=1).update(counter=F("counter") + 1)

result = await Book.annotate(count=Count("id")).group_by("author_id").values("author_id", "count")

await Model.bulk_create([obj1, obj2], batch_size=100)
await Model.bulk_update([obj1, obj2], fields=["name"], batch_size=100)
```

### Fetching Relations

| Method                             | Scope                       | When to use                       |
| ---------------------------------- | --------------------------- | --------------------------------- |
| `select_related("fk_field")`       | QuerySet (JOIN)             | FK/O2O, small result sets         |
| `prefetch_related("m2m_field")`    | QuerySet (separate queries) | M2M, reverse FK, nested           |
| `await obj.fetch_related("field")` | Single instance             | After you already have the object |

```python
from tortoise.query_utils import Prefetch

# Custom prefetch filtering
await Tournament.all().prefetch_related(
    Prefetch("events", queryset=Event.filter(name="First"))
)

# Cross-relation filtering
await Team.filter(events__tournament__id=tournament.id)
```

## Transactions

```python
from tortoise.transactions import in_transaction, atomic

# Context manager
async with in_transaction() as connection:
    await MyModel.create(name="foo")

# Decorator
@atomic()
async def create_pair(data):
    user = await User.create(**data)
    await Profile.create(user=user)
```

Nested `in_transaction` blocks create savepoints. Multi-DB: pass `connection_name`.

## Signals

```python
from tortoise.signals import pre_save, post_save, pre_delete, post_delete

@post_save(MyModel)
async def on_save(sender, instance, created, using_db, update_fields):
    if created:
        print(f"New: {instance.id}")
```

`created` on `post_save`: INSERT vs UPDATE. A handler fires only after its module is imported.

## Pydantic Integration

```python
from tortoise.contrib.pydantic import pydantic_model_creator, pydantic_queryset_creator

Tournament_Pydantic = pydantic_model_creator(Tournament)
Tournament_PydanticIn = pydantic_model_creator(Tournament, exclude_readonly=True)

# Serialization (read-only -- no deserialization)
pydantic_obj = await Tournament_Pydantic.from_tortoise_orm(instance)
pydantic_obj = await Tournament_Pydantic.from_queryset_single(Tournament.get(id=1))
```

Before full ORM init: `Tortoise.init_models(["app.models"], "models")`. Computed fields in `PydanticMeta` need explicit return type hints.

## Testing (v1.x, pytest only)

The unittest-based `TestCase`/`IsolatedTestCase` classes are removed in v1.0+.

```python
import pytest_asyncio
from tortoise.contrib.test import tortoise_test_context

@pytest_asyncio.fixture
async def db():
    async with tortoise_test_context(["myapp.models"]) as ctx:
        yield ctx

@pytest.mark.asyncio
async def test_create(db):
    user = await User.create(name="Test")
    assert user.name == "Test"
```

## Migrations (v1.1.7 built-in)

Aerich is legacy. Tortoise v1.1.7 has a built-in migration system:

```bash
tortoise init                    # create migration packages
tortoise makemigrations          # detect changes
tortoise migrate                 # apply
tortoise downgrade models        # reverse
tortoise history                 # list applied
```

Data migrations: `RunPython` (with `apps.get_model()`) or `RunSQL`.

## Reference

`references/api-reference.md`: complete field reference, DB URL formats, engine names, exception hierarchy, validators, advanced patterns.
