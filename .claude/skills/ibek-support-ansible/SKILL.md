---
name: ibek-support-ansible
description: Ansible build system for EPICS support modules — use when creating or editing install.yml files, debugging build failures, or modifying the ansible roles that compile support modules in containers.
---

# ibek-support Ansible Build System

Reference for the ansible-based build system that compiles EPICS support modules
inside containers.

---

## Key files

- **Variable defaults + docs:** `ibek-support/_ansible/roles/support/vars/main.yml`
  — all install.yml variables with defaults and examples. Read this first.
- **JSON schema:** `ibek-support/_scripts/support_install_variables.json`
  — validates install.yml files. Must be kept in sync with vars/main.yml.
- **Build pipeline:** `ibek-support/_ansible/roles/support/tasks/main.yml`
  — orchestrates the build steps.
- **Global variables:** `ibek-support/_ansible/group_vars/all.yml`
  — paths (`support_folder`, `local_path`, `release_file`), arch flags
  (`is_rtems`, `is_linux`), and config paths (`config_linux_host`).
- **Entry point:** `ibek-support/_ansible/ansible.sh <module|all|ioc>`

---

## Build pipeline sequence

```
1. system.yml     — apt install packages
2. clone.yml      — git clone
3. tasks.yml      — pre-build ansible tasks
4. pre_build.yml  — comment_out, patch, scripts, bash  (post_build: false)
5. release.yml    — configure/RELEASE
6. build.yml      — make
7. post_build.yml — RELEASE.shell, libs/dbds, patch, scripts, bash  (post_build: true)
8. tasks.yml      — post-build ansible tasks
9. runtime.yml    — copy runtime files
```

Items default to pre-build. Set `post_build: true` to run after make.

---

## Adding new install.yml variables

Always update two files:
1. `_ansible/roles/support/vars/main.yml` — default value + comment docs
2. `_scripts/support_install_variables.json` — JSON schema type def + property

Then add the corresponding ansible task in `pre_build.yml` and/or `post_build.yml`.

---

## Common patterns

- **Conditional on arch:** `when: "{{ is_linux }}"` or `when: "{{ is_rtems }}"`
- **Inline shell:** use `bash` entries (`cmd`, `when`, `post_build`). CWD is `local_path`.
- **Script files:** use `scripts` entries (`path` relative to `ibek-support/<module>/`)
- **Complex ansible steps:** use `tasks` entries pointing to separate `*_task.yml` files
  (useful when you need ansible features like `creates`, `register`, `failed_when`)
- **Module discovery for `all`:** parses `RUN ansible.sh` lines from the Dockerfile

## Shipping extra templates/db files (DLS additions not in upstream)

**Last resort.** This forks a file away from its upstream module and makes
ibek-support carry DLS content. Before proposing it, surface the problem to
the user and check the preferred options first:

1. **Upstream the file** — open a PR against the module's upstream repo.
   Best long-term answer; aligns with the open-source transition.
2. **Redesign around existing upstream files** — drop the broken entity or
   swap its `databases` reference to something upstream already ships
   (e.g. replaced `devIocStats.devIocStatsHelper` with
   `devIocStats.iocAdminSoft`, which only loads upstream db files).
3. **Drop the functionality** if the file contributes only GUI metadata
   and no records (e.g. the former `iocGui.db`).

Only fall through to shipping via ibek-support if (1)–(3) aren't viable, and
flag the choice to the user before making the change.

### The mechanism

`EPICS_DB_INCLUDE_PATH` is built from `{{ support_folder }}/*/db` only. Files
placed at `ibek-support/<module>/*.template` are NOT on msi's search path on
their own — runtime.yml only links `.ibek.support.yaml`, `.pvi.device.yaml`,
and `.req` files out of the ibek-support folder.

1. Drop the file in `ibek-support/<module>/<file>.template`.
2. In the entity model YAML, reference it with just the filename (no
   `$(MODULE)/db/` prefix) — see `pmac/moveAxesToSafe.template` as prior art.
3. Add a `bash` post_build entry to the module's `.install.yml` copying the
   file into the built module's `db/` folder:

   ```yaml
   bash:
     - cmd: cp {{ ibek_support_folder }}/<file>.template db/
       post_build: true
   ```

Prior art: `ibek-support/ether_ip/ether_ip_plcInfo.template` + its install.yml.
