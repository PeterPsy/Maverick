# Default workspace host privileges

Every self-hosted Linux server that enables the `default` operator workspace
with `full-access` must give its actual runtime account non-interactive root
authority. Use a named, non-root account with `NOPASSWD: ALL` sudo access.
This is a required installation acceptance step, on a fresh server and after a
server move.

The account name is installation-specific: `ubuntu` on the predecessor and
`loopino` on the current destination have the same privilege model. The
`--service-user` installer option selects the account; its default is `loopino`.
The web login `admin`, membership of the Linux `sudo` group, and the Chat
full-access badge do not establish passwordless root authority.

Core and providers continue to run as the selected account. Shell operations on
protected files, packages, Docker, firewall rules or system services use
`sudo -n`. Direct filesystem tools retain that account's normal Linux
permissions. The OS grant belongs to the account, not to one conversation.
Core CLI/MCP/API authorization remains independently enforced.

## Identify the deployed account

After service installation, run these checks from the installation checkout:

```sh
loopino_install_root="$(pwd -P)"
loopino_core_unit=loopino-core.service
loopino_runtime_user="$(systemctl show "$loopino_core_unit" --property=User --value)"
systemctl show "$loopino_core_unit" --property=User --property=Group \
  --property=NoNewPrivileges --property=RootDirectory --property=RootImage
getent passwd "$loopino_runtime_user"
```

Use the deployed unit name when the installation uses a custom service layout.
Confirm that `User` is the reviewed non-root runtime account before granting
anything. Do not substitute the current SSH login, the web admin, a historical
UID, or an account copied from another server.

## Prepare the sudo rule

This is an explicit installation-owner action. The current installer selects the
service identity but does not create this sudo rule or gate its health result on
root access. An installer exit code of zero does not complete operator workspace
acceptance; complete this step and the live checks below.

From a trusted administrative terminal, verify that the installation root and
its `installation/` ancestors are real, root-owned directories without group or
world write permission. Use an installation-owned backing file and an exact OS
symlink; preserve unrelated sudo rules. For a new registration:

```sh
loopino_sudo_policy="$loopino_install_root/installation/sudoers/loopino-runtime-admin"
sudo install -d -o root -g root -m 0750 "$loopino_install_root/installation/sudoers"
sudo visudo -f "$loopino_sudo_policy"
```

Enter exactly the selected account's rule. For the default `loopino` account:

```sudoers
loopino ALL=(ALL) NOPASSWD: ALL
```

For `ubuntu` or another reviewed account, replace only the account name. Then:

```sh
sudo chown root:root "$loopino_sudo_policy"
sudo chmod 0440 "$loopino_sudo_policy"
sudo visudo -cf "$loopino_sudo_policy"
sudo ln -s -- "$loopino_sudo_policy" /etc/sudoers.d/loopino-runtime-admin
sudo visudo -c
```

The link command deliberately refuses an existing entry. If one exists, inspect
its exact target and backing file rather than replacing it. If complete policy
validation fails, remove only the newly created, exact registration and correct
the candidate before retrying. Never overwrite another installation's rule.
Revoke this grant by removing its reviewed exact symlink and revalidating the
remaining policy. Backing files stay in ignored `installation/` state.

On a migrated/chroot/container installation, install and validate the policy in
the actual runtime's execution root. UID 0 inside an isolated root does not by
itself prove control of the outer host. Verify the required services from an
actual agent session; record any remaining boundary explicitly.

## Required live acceptance

From the administrative terminal:

```sh
sudo -u "$loopino_runtime_user" -- sudo -n -l
sudo -u "$loopino_runtime_user" -- sudo -n id -u
```

The policy must include `NOPASSWD: ALL` and the UID check must return `0` without
a password or approval prompt. Changing Core's service user to root is not the
installation procedure. A global `NoNewPrivileges=yes` on Core would prevent
this elevation; retain privilege restrictions on sandbox children.

For every enabled native engine and the hosted shell path in use, run these
read-only checks inside a real `default` full-access chat:

```sh
id -un
id -u
sudo -n id -u
sudo -n systemctl is-active loopino-core.service
```

Expect the selected non-root user and its UID, then `0` and `active`. Use the
deployed unit name. A root SSH test alone does not verify a provider's execution
path. Verify access to the host operations required by the deployment, such as
Docker, firewall status and journal reads, without changing their configuration.

Also verify the sandbox boundary with a real sandbox launch: it must retain
`NoNewPrivs: 1`, hide host sudoers/private installation paths, and refuse sudo
elevation even when the sudo binary and its libraries are available. A workspace
other than `default` must resolve a full-access request to sandbox. Do not grant
other workspaces host administration or disable their confinement.

Record the service identity, sudo rule, actual native/hosted checks and sandbox
result as deployment evidence. Missing sudo access or a failed sandbox check
leaves operator workspace acceptance incomplete, regardless of the Chat badge,
HTTP health or DNS/TLS readiness.
