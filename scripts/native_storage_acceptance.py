"""Current-instance shared ACL and private directory isolation acceptance."""

import argparse
import secrets
from pathlib import Path

from native_acceptance_common import as_user, execute


def check_reader_file(f, reader, path):
    result = as_user(
        reader,
        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); f=p.open('a'); f.write('denied'); f.close()",
        path,
    )
    f.check(result.returncode != 0, "acl:reader_existing_file_write_denied")
    result = as_user(
        reader, "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())", path
    )
    f.check(
        result.returncode == 0 and result.stdout.strip() == "shared",
        "acl:reader_denial_preserves_existing_content",
    )


def acl(f):
    accounts = [
        f.create(
            role,
            password=secrets.token_urlsafe(24) + "9!aB",
            require_password_change=False,
        )
        for role in ("writer", "reader", "outsider")
    ]
    changes = {
        "name": "gpupmqa_" + f.suffix,
        "members": [
            dict(username=accounts[0]["username"], permission="write"),
            dict(username=accounts[1]["username"], permission="read"),
        ],
    }
    preview = f.agent.call("preview_share_change", {"changes": changes})
    share = f.agent.call(
        "execute_share_change",
        {
            "changes": changes,
            "token": preview["token"],
            "reason": "Native ACL acceptance",
        },
    )
    f.artifacts.append({"share": share["path"], "groups": [share["reader_group"], share["writer_group"]]})
    nested = Path(share["path"]) / "inherited" / "proof.txt"
    result = as_user(
        accounts[0],
        "import os,pathlib,sys; os.umask(0o077); p=pathlib.Path(sys.argv[1]); p.parent.mkdir(); p.write_text('shared')",
        nested,
    )
    f.check(result.returncode == 0, "acl:writer_creates_nested_file")
    for index, readable in ((1, True), (2, False)):
        result = as_user(
            accounts[index],
            "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())",
            nested,
        )
        f.check(
            (result.returncode == 0 and result.stdout.strip() == "shared")
            if readable
            else result.returncode != 0,
            "acl:inherited_reader_access" if readable else "acl:outsider_denied",
        )
        result = as_user(
            accounts[index],
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('denied')",
            nested.parent / f"denied{index}",
        )
        f.check(result.returncode != 0, f"acl:{index}:write_denied")
    check_reader_file(f, accounts[1], nested)
    result = as_user(
        accounts[0],
        "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('updated')",
        nested,
    )
    f.check(result.returncode == 0, "acl:writer_updates_inherited_file")
    # Revocation affects fresh processes; no existing user sessions are terminated.
    params = {
        "id": share["id"],
        "revision": share["revision"],
        "changes": {"members": [dict(username=accounts[0]["username"], permission="write")]},
        "reason": "Native member revocation acceptance",
    }
    preview = f.agent.call("preview_share_change", params)
    share = f.agent.call("execute_share_change", dict(params, token=preview["token"]))
    result = as_user(
        accounts[1], "import pathlib,sys; pathlib.Path(sys.argv[1]).read_text()", nested
    )
    f.check(result.returncode != 0, "acl:revoked_reader_fresh_process_denied")
    for permission in ("write", "read"):
        params = dict(id=share["id"], revision=share["revision"], changes={"members": [
            dict(username=accounts[0]["username"], permission="write"),
            dict(username=accounts[1]["username"], permission=permission),
        ]}, reason="Native member permission transition")
        preview = f.agent.call("preview_share_change", params)
        share = f.agent.call("execute_share_change", dict(params, token=preview["token"]))
        result = as_user(accounts[1], "import pathlib,sys; pathlib.Path(sys.argv[1]).open('a').write('x')", nested)
        f.check((result.returncode == 0) == (permission == "write"), "members:transition_" + permission)
    listed = next(s for s in f.agent.call("list_shares") if s["id"] == share["id"])
    f.check({m["username"]:m["permission"] for m in listed["members"]} == {
        accounts[0]["username"]:"write", accounts[1]["username"]:"read"}, "members:native_readback")
    internal = [g for g in f.agent.call("list_system_groups", {"scope":"all"}) if g.get("share_owner") == share["name"]]
    f.check(len(internal) == 2 and all(not g["assignable"] for g in internal), "members:internal_groups_not_assignable")
    other_changes = dict(name="gpupmqa_other_" + f.suffix, members=[])
    preview = f.agent.call("preview_share_change", {"changes":other_changes})
    other = f.agent.call("execute_share_change", dict(changes=other_changes, token=preview["token"], reason="Native cross-project isolation"))
    f.artifacts.append({"share":other["path"], "groups":[other["reader_group"],other["writer_group"]]})
    f.check(as_user(accounts[0], "import os,sys; os.listdir(sys.argv[1])", other["path"]).returncode != 0, "members:cross_project_isolation")
    for field in ("home", "data_dir"):
        private = Path(accounts[0][field])
        f.check(private.stat().st_mode & 0o777 == 0o700, f"acl:private_{field}_0700")
        f.check(
            as_user(
                accounts[1], "import os,sys; os.listdir(sys.argv[1])", private
            ).returncode
            != 0,
            f"acl:private_{field}_denied",
        )




def acceptance(f, args):
    acl(f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--checks", choices=("acl",), default="acl")
    parser.add_argument("--output")
    raise SystemExit(execute(parser.parse_args(), acceptance))
