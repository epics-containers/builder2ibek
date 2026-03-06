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
