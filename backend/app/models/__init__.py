"""
Core schema, Master Spec §9. Each module below owns one table group from
that section. Import them all here so `from app.models import *` (and
alembic autogenerate) sees the complete metadata.
"""
from app.models.enums import CoverageTier, CorporateActionType, ProvenanceTier  # noqa: F401
from app.models.securities import Security  # noqa: F401
from app.models.prices import PriceDaily  # noqa: F401
from app.models.corporate_actions import CorporateAction  # noqa: F401
from app.models.fundamentals import Fundamental  # noqa: F401
from app.models.float_data import FloatData  # noqa: F401
from app.models.macro import MacroSeries  # noqa: F401
from app.models.data_quality import DataAlert  # noqa: F401
from app.models.registry import IssuerRegistry  # noqa: F401
from app.models.national_projects import NationalProject, NationalProjectTickerImpact  # noqa: F401
from app.models.portfolio import PortfolioSnapshot, PortfolioPosition  # noqa: F401
