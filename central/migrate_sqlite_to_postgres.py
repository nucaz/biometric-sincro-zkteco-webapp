"""
Copia todos los datos reales desde el SQLite nativo (central/attendance.db)
hacia el PostgreSQL del despliegue Docker, tabla por tabla, respetando el
orden de llaves foráneas y conservando los IDs originales (para que las
auditorías, los vínculos empleado-dispositivo, etc. no queden rotos).

NUNCA escribe en el origen SQLite -- solo hace SELECT ahí. Por seguridad,
corré esto contra una COPIA del archivo real (ver deploy/docker/
migrar_servidor_central.ps1), no contra el .db mientras el servicio nativo
todavía lo está escribiendo.

Uso:
    DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/asistencia \
        python -m central.migrate_sqlite_to_postgres --sqlite ruta\\al\\attendance.db

Por defecto se niega a tocar un Postgres que ya tenga filas (protección
contra correrlo dos veces y duplicar todo) -- pasa --force para saltarte
eso a propósito.
"""
import argparse
import os
import re
import sys

from sqlalchemy import create_engine, select, insert, text, inspect


def _mask_url(url):
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--sqlite",
        default=os.path.join(os.path.dirname(__file__), "attendance.db"),
        help="Ruta al archivo SQLite de origen (default: central/attendance.db)",
    )
    parser.add_argument(
        "--to",
        default=os.environ.get("DATABASE_URL"),
        help="URL de PostgreSQL destino (default: variable de entorno DATABASE_URL)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Permite migrar aunque el destino ya tenga filas (las agrega encima -- puede duplicar datos)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="No pedir confirmación antes de empezar",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Filas por lote al insertar (default: 500)",
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    if not os.path.isfile(args.sqlite):
        print(f"ERROR: no existe el archivo SQLite de origen: {args.sqlite}", file=sys.stderr)
        sys.exit(1)

    if not args.to:
        print("ERROR: falta el destino -- pasá --to o definí la variable de entorno DATABASE_URL.", file=sys.stderr)
        sys.exit(1)

    if args.to.startswith("sqlite"):
        print("ERROR: el destino no puede ser otro SQLite -- este script es específicamente SQLite -> PostgreSQL.", file=sys.stderr)
        sys.exit(1)

    is_postgres = args.to.startswith("postgresql")

    print(f"Origen (SQLite, solo lectura): {args.sqlite}")
    print(f"Destino: {_mask_url(args.to)}")
    if not args.yes:
        answer = input("¿Continuar con la migración? (escribí 'si' para confirmar): ").strip().lower()
        if answer not in ("si", "sí", "s", "yes", "y"):
            print("Cancelado -- no se tocó nada.")
            sys.exit(0)

    # Import diferido: central.models registra las tablas sobre Base al
    # importarse, y necesitamos eso ANTES de poder usar Base.metadata, pero
    # DESPUÉS de haber validado los argumentos (para fallar rápido con un
    # mensaje claro si falta algo, sin esperar a que se conecte nada).
    from central import models  # noqa: F401
    from central.db import Base

    src_engine = create_engine(f"sqlite:///{args.sqlite}")
    dst_engine = create_engine(args.to)

    print("\nCreando el esquema en el destino (si ya existe, no hace nada)...")
    Base.metadata.create_all(dst_engine)

    tables = Base.metadata.sorted_tables  # ya vienen en orden de dependencia (FKs primero)

    if not args.force:
        with dst_engine.connect() as dst_conn:
            non_empty = []
            for table in tables:
                count = dst_conn.execute(select(table)).fetchmany(1)
                if count:
                    non_empty.append(table.name)
            if non_empty:
                print(
                    f"\nERROR: el destino ya tiene datos en: {', '.join(non_empty)}. "
                    "Si de verdad querés migrar igual (puede duplicar filas), volvé a "
                    "correr con --force. Si fue un error, vaciá el destino primero.",
                    file=sys.stderr,
                )
                sys.exit(1)

    print("\nCopiando datos...\n")
    # El origen puede ser un SQLite de una versión anterior de la app,
    # creado antes de que existiera alguna tabla nueva (ej. api_tokens,
    # device_commands) -- init_db() las agrega recién la próxima vez que
    # arranca el proceso, así que un .db copiado mientras el servicio
    # estaba apagado puede no tenerlas todavía. No es un error: tratarla
    # como "nada que migrar" para esa tabla, no abortar todo.
    src_inspector = inspect(src_engine)
    src_table_names = set(src_inspector.get_table_names())

    summary = []
    with src_engine.connect() as src_conn, dst_engine.begin() as dst_conn:
        for table in tables:
            if table.name not in src_table_names:
                print(f"  {table.name:<24} (no existe en el origen -- nada que migrar, OK)")
                summary.append((table.name, 0, 0))
                continue

            # Mismo caso que arriba pero a nivel de COLUMNA: una columna
            # agregada después de que se creó este SQLite (ej.
            # devices.agent_name) tampoco está ahí todavía. Seleccionar
            # solo las columnas que de verdad existen en el origen -- las
            # que falten quedan con su default de SQLAlchemy (todas estas
            # columnas "agregadas después" son nullable o tienen default,
            # por diseño, ver central/db.py).
            src_columns = {c["name"] for c in src_inspector.get_columns(table.name)}
            cols_to_select = [c for c in table.columns if c.name in src_columns]
            missing_cols = [c.name for c in table.columns if c.name not in src_columns]
            if missing_cols:
                print(f"  {table.name:<24} (sin columnas {', '.join(missing_cols)} en el origen -- quedan con su valor por defecto)")

            rows = [dict(r) for r in src_conn.execute(select(*cols_to_select)).mappings().all()]
            if rows:
                for i in range(0, len(rows), args.batch_size):
                    batch = rows[i : i + args.batch_size]
                    dst_conn.execute(insert(table), batch)

            # Reajustar la secuencia autoincremental de Postgres para la
            # próxima fila nueva -- sin esto, el primer INSERT hecho desde
            # la app después de migrar intentaría reusar un id que ya
            # insertamos a mano acá y fallaría por llave duplicada.
            if is_postgres and len(table.primary_key.columns) == 1:
                pk_col = list(table.primary_key.columns)[0]
                seq_name = dst_conn.execute(
                    text("SELECT pg_get_serial_sequence(:t, :c)"),
                    {"t": table.name, "c": pk_col.name},
                ).scalar()
                if seq_name:
                    dst_conn.execute(
                        text(
                            f"SELECT setval(:seq, COALESCE((SELECT MAX({pk_col.name}) FROM {table.name}), 1), "
                            f"(SELECT MAX({pk_col.name}) FROM {table.name}) IS NOT NULL)"
                        ),
                        {"seq": seq_name},
                    )

            target_count = dst_conn.execute(select(table)).fetchall()
            summary.append((table.name, len(rows), len(target_count)))
            status = "OK" if len(rows) == len(target_count) else "DESAJUSTE"
            print(f"  {table.name:<24} origen={len(rows):<8} destino={len(target_count):<8} {status}")

    print("\n=== Resumen ===")
    mismatches = [row for row in summary if row[1] != row[2]]
    if mismatches:
        print(f"ATENCIÓN: {len(mismatches)} tabla(s) con conteos que no calzan -- revisar antes de dar por buena la migración.")
        sys.exit(1)
    else:
        print(f"Todo calza: {len(summary)} tablas migradas correctamente.")


if __name__ == "__main__":
    main()
