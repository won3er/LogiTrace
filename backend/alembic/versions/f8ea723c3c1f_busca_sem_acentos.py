"""busca sem acentos

Revision ID: f8ea723c3c1f
Revises: 91fbbb5d753b
Create Date: 2026-10-27 12:53:49.852383

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = 'f8ea723c3c1f'
down_revision: Union[str, Sequence[str], None] = '91fbbb5d753b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    # wrapper IMMUTABLE permite uso em índices e buscas por nome sem acento
    op.execute(
        """
        CREATE OR REPLACE FUNCTION unaccent_name(text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        AS $$ SELECT lower(public.unaccent('public.unaccent'::regdictionary, $1)) $$
        """
    )
    op.execute("CREATE INDEX ix_municipality_name_unaccent ON municipality (unaccent_name(name))")
    op.execute("CREATE INDEX ix_facility_name_unaccent ON facility (unaccent_name(name))")
    op.execute("CREATE UNIQUE INDEX ix_network_edge_version_idx ON network_edge (version_id, edge_idx)")
    op.execute("CREATE UNIQUE INDEX ix_network_node_version_idx ON network_node (version_id, node_idx)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_network_node_version_idx")
    op.execute("DROP INDEX IF EXISTS ix_network_edge_version_idx")
    op.execute("DROP INDEX IF EXISTS ix_facility_name_unaccent")
    op.execute("DROP INDEX IF EXISTS ix_municipality_name_unaccent")
    op.execute("DROP FUNCTION IF EXISTS unaccent_name(text)")
