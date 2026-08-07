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

### Module order in a generic IOC Dockerfile

Each `RUN ansible.sh <module>` is a separate layer, so a module must be built
**after** everything its dbd or link line needs. The authoritative order is the
`core` group in `ibek-support/build-groups.yml`:

```
calc  sscan  asyn  busy  autosave  sequencer  std
```

Two dependencies in there are easy to miss, and both were shipped broken:

- **`std` must follow `asyn`.** `stdInclude.dbd` includes `asyn.dbd`, so building
  it first gives `dbdExpand.pl: Can't find file 'asyn.dbd'`.
- **`std` needs `sequencer`.** `std_SRCS` includes `femto.st` and `delayDo.st`,
  which need `snc` to become objects, and `std_LIBS += asyn seq pv`. Without it:
  `make: *** No rule to make target 'femto.o', needed by 'libstd.a'`. No IOC uses
  the sequencer directly, which is exactly why it gets left out.

A missing-dependency failure surfaces at whichever module is built too early, not
at the one that is absent — read the error for what it *wanted*, not where it
stopped.

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

### `patch_lines` appends at EOF — beware Makefiles

`patch_lines` is ansible `lineinfile`, so when its `regexp` matches nothing it
**appends the line at the end of the file** rather than failing. That is silent
and usually harmless, but it is wrong whenever position matters.

Most EPICS Makefiles end with `include $(TOP)/configure/RULES*`, and make
expands many variables *while processing that include* — `<dir>_DEPEND_DIRS` in
`RULES_DIRS`, for example. A line appended after it has no effect at all, and
the build fails somewhere unrelated.

Use `patch_blocks` when the line must land in a particular place; it supports
`insertafter`, so anchor on something stable near the top:

```yaml
patch_blocks:
  - path: <module>App/Makefile
    insertafter: '^include \$\(TOP\)/configure/CONFIG$'
    marker: "# {mark} <why>"
    block: |
      Db_DEPEND_DIRS = src
```

Verify the anchor matches exactly once — `blockinfile` inserts after the *last*
match.

### Installing a tool rather than a support module

Some entries under `ibek-support/` install a build time tool with no repo to
clone and no `make` to run — `vdct` (VisualDCT) is the first. The role has no
"skip build" switch and `build.yml` runs `make clean` unconditionally, so run
only the phases you need by tag:

```dockerfile
COPY ibek-support/vdct/ vdct
RUN ansible.sh vdct --tags system,pre_build_tasks
```

`ansible.sh` passes trailing arguments through to `ansible-playbook` untouched.
The `system` tag gives you `apt_developer` and `download_extras`;
`pre_build_tasks` gives you `tasks` entries. Clone, release, build and the
runtime phases are all skipped.

Do the real work in a `tasks` file, not `bash`/`scripts` entries — those run
with `chdir: local_path`, which does not exist when nothing was cloned.

Put such tools immediately after the `COPY ibek-support/_ansible` line so every
later module can use them.

---

## Generic IOC image publishing — on GitHub, tags only

A generic IOC repo's `.github/workflows/build.yml` builds and tests on every
push, but both the "Push developer image" and "Push runtime image" steps are
gated on:

```yaml
if: ${{ github.event_name == 'push' && github.ref_type == 'tag' }}
```

So on GitHub **a branch push publishes nothing**.

This is easy to get wrong because the `docker/metadata-action` step is *not*
gated — it still computes `ghcr.io/epics-containers/<repo>-developer:<branch>`
and prints it into the CI log. Seeing that tag in a successful branch build is
not evidence that an image exists.

DLS GitLab behaves differently: `.gitlab/kanikobuild.sh` pushes on every
commit, using the branch name as the image tag when `CI_COMMIT_TAG` is unset
(untagged commits go to the work registry, tagged ones to prod). So branch
images do exist there.

Consequence when layering generic IOCs (`ARG DEVELOPER=.../ioc-<base>-developer:<tag>`):
if the base lives on GitHub you cannot test a downstream IOC against a branch
build of it. Cut and push a tag on the base repo first, then point `DEVELOPER`
at that tag.
