"""Initial API business schema.

Revision ID: 0001
"""

from alembic import op
from gpupm.db.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(op.get_bind())


def downgrade():
    raise RuntimeError(
        "Downgrade would destroy account/task audit history; restore a pre-upgrade backup instead."
    )
