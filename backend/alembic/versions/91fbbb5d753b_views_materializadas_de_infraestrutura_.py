"""views materializadas de infraestrutura por municipio

Revision ID: 91fbbb5d753b
Revises: 2d6d1ff0ac6d
Create Date: 2026-10-27 12:51:47.533005

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = '91fbbb5d753b'
down_revision: Union[str, Sequence[str], None] = '2d6d1ff0ac6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensão de infraestrutura linear por município (pré-agregada: interseção espacial é custosa).
    # Criada vazia; preenchida por `python -m app.cli refresh-stats` após cada ingestão.
    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_municipality_infra AS
        SELECT m.code,
               s.modal,
               SUM(ST_Length(ST_Intersection(s.geom, m.geom)::geography)) / 1000.0 AS km,
               SUM(CASE WHEN s.surface IN ('Duplicada','Pavimentada','Em obras de duplicação')
                        THEN ST_Length(ST_Intersection(s.geom, m.geom)::geography) ELSE 0 END) / 1000.0 AS km_paved
        FROM municipality m
        JOIN infra_segment s ON ST_Intersects(s.geom, m.geom)
        WHERE s.modal IN ('road', 'rail', 'waterway')
          AND s.record_class = 'official'
          AND coalesce(s.surface, '') NOT IN ('Planejada', 'Em obras de implantação')
        GROUP BY m.code, s.modal
        WITH NO DATA
        """
    )
    op.execute("CREATE UNIQUE INDEX ix_mv_municipality_infra ON mv_municipality_infra (code, modal)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_municipality_infra")
