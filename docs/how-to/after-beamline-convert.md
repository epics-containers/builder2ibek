# After a Beamline Auto-Conversion

The `beamline-convert` process gives you a set of ibek IOCs with their
`ioc.yaml` files with compatible support in `ibek-support` and `ibek-support-dls`.

This is a solid starting point, but it is **not** a fully converted beamline. The steps below complete the conversion — and teach you more about how epics-containers works along the way.

## 1. Split IOCs by device

The auto-conversion mirrors the original builder layout, which often packs
many devices into a small number of IOCs (e.g. `BL21I-MO-IOC-01`). In
epics-containers the convention is **one IOC per device**.

Break each converted IOC into individual IOCs, one per physical device or
logical unit. Name them after the device they serve rather than using generic
numbering:

| Before (builder)    | After (epics-containers)            |
|---------------------|-------------------------------------|
| `BL21I-MO-IOC-01`  | `BL21I-MO-STEP-01` (geobrick 1)    |
|                     | `BL21I-MO-STEP-02` (geobrick 2)    |
|                     | `BL21I-MO-STEP-03` (geobrick 3)    |
| `BL21I-EA-IOC-01`  | `BL21I-EA-RGA-01` (RGA analyser)   |
|                     | `BL21I-EA-CRYO-01` (cryo cooler)   |

Each new IOC gets its own folder in the services repo with its own `ioc.yaml`
and `values.yaml`.

## 2. Plan the split around Generic IOC reuse

The goal of epics-containers is to have a small number of **Generic IOC**
container images that are shared across multiple IOC instances and multiple beamlines. When deciding how to split your IOCs, think about which support modules each one needs:

- **Prefer existing Generic IOCs.** If there is already a published Generic IOC
  that contains all the support modules your device needs, use it. Check the
  [epics-containers GitHub packages](https://github.com/orgs/epics-containers/packages?tab=packages&q=ioc-)
  for available images.

- **Create reusable new Generic IOCs.** When no existing image fits, plan to
  create a new one with a concise, coherent set of support modules that is
  likely to be useful for other IOC instances — on your beamline and others.

- **One-off containers as a last resort.** For genuinely complex scenarios where
  a single IOC really does need an unusual mix of support, you can create a
  unique Generic IOC. But exhaust the options above first.

- **Split out CA-based components.** Anything that is beamline specific and uses Channel Access to communicate — especially aSub records, should go into a separate, beamline-specific container build. This keeps your reusable Generic IOCs clean.

- **Retire Beamline Support modules** if at all possible, don't keep a beamline support module. If you have asub records that cannot be refactored then you will need to make a beamline specific support Generic IOC. But note that many support modules are just DB templates and those could be dropped into individual IOC instance config folders instead of a shared support module.

## 3. Move support YAML to public repositories

The auto-conversion places new support YAML in `ibek-support-dls/` and points
`install.yml` at the internal DLS support module. For each module, work through
the following options in order of preference:

### 3a. Use upstream public sources

If the support module exists upstream (in
[epics-modules](https://github.com/epics-modules),
[areaDetector](https://github.com/areaDetector), or another public
organisation), move the support YAML folder from `ibek-support-dls/` to
`ibek-support/` and update `install.yml` to point at the latest upstream
release.

### 3b. Use DiamondLightSource GitHub

If the module is already published under the
[DiamondLightSource](https://github.com/DiamondLightSource) GitHub
organisation, use `ibek-support/` and point at that repo. **Make sure the
GitHub version is up to date with the internal GitLab version** before
switching.

### 3c. Open-source internal modules

If a module is currently internal-only but would be useful to the wider EPICS
community, open-source it under the DiamondLightSource organisation. See the
[Generic IOC tutorial](https://epics-containers.github.io/main/tutorials/generic_ioc.html)
for guidance on publishing.

### 3d. Keep genuinely internal modules in ibek-support-dls

Some modules are specific to DLS infrastructure and will never be useful
externally. These stay in `ibek-support-dls/`.

## 4. Point each IOC at a Generic IOC image

Each IOC's `values.yaml` must reference the Generic IOC container image that
includes all the support it needs. If a suitable image already exists, point at
its latest release tag. If not, create a new Generic IOC — see the
[Generic IOC tutorial](https://epics-containers.github.io/main/tutorials/generic_ioc.html).

(if you are making a new Generic IOC, then this stage will have to wait until 6. below when you have released the new image and can point at its tag)

## 5. Test in a devcontainer

Before deploying, verify that your IOC works inside a devcontainer. Use
`ibek dev instance` to point the Generic IOC's devcontainer at your IOC
instance's `ioc.yaml` and confirm it starts correctly:

```bash
ibek dev instance /path/to/ioc-instance
```

This symlinks `/epics/ioc/config` to your instance config directory, letting
you iterate quickly on the `ioc.yaml` without rebuilding the container.

## 6. Release and deploy

Once everything is working in the devcontainer:

1. **Release the Generic IOC** so its image is published to the container
   registry (unless one already existed).
2. **Update `values.yaml`** in the services repo to reference the newly
   released image tag.
3. **Deploy and test on the beamline** to confirm the IOC behaves correctly in
   production.
