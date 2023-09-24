Specific Convertors for Builder2Ibek
====================================

When converting from Builder XML to ibek IOC YAML the most straight forward
support module's will convert directly with no additional configuration.

However, where there has been some clever use of calucalted fields or
other features in builder.py it may be necessary to provide a specific
convertor.

To do so just add a module to this directory with the name of the support
module you wish to convert with suffix '.py'.

See the example pmac.py for details of what to provide in the file.
