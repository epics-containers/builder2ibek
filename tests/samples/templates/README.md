# Support Db sample templates

In order to test the full cycle of

- conversion of XML builder files to ibek IOC YAML,
- generation of ioc.subst from IOC YAML,
- expansion of ioc.subst to ioc.db

we require the DB template files for the second step.

This test performs the above steps: `tests/test_db_generation.py`

At present these files were copied out of the latest ioc-dlsvmevac in order to test the conversion of IOCs for any DLS vacuum.

Potentially this could be extended to all of the generic IOCs used in the XML files in tests/samples. This would require that ibek-support* tracked the most recent versions of support modules and that this folder was kept up to date with the latest versions of template files from referenced support modules.

This is for review as it sounds like a mainenance headache.

Potentially these tests could be moved to the individual ioc-xxx projects or the tests here could use the generic IOC containers themselves. (second is preferred - I like being able to assess the damage caused by changes to ibek-support* or changes to builder2ibek, all in one place)
