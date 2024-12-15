# regenerate the tests results files

# caution: validate that the yaml diff looks good before committing these
# changes

for x in *.xml; do
  y=$(echo $x | sed -e 's/\.xml/\.yaml/' -e 's/.*/\L&/g')
  echo converting $x to $y
  builder2ibek xml2yaml $x --yaml $y
done
