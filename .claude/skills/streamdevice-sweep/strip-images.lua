-- Drop every image from a pandoc document and record what was dropped.
--
-- ibek-runtime-streamdevice is a PUBLIC repo and DLS documentation folders
-- routinely embed manufacturer figures that DLS has no right to redistribute.
-- An honest gap beats a broken image link, so the figures are listed at the end
-- of the converted document instead of being copied.

local dropped = {}

function Image(el)
    local src = el.src or "?"
    local alt = pandoc.utils.stringify(el.caption or "")
    table.insert(dropped, alt ~= "" and (alt .. " (" .. src .. ")") or src)
    return {}
end

function Pandoc(doc)
    if #dropped == 0 then
        return doc
    end
    local blocks = doc.blocks
    table.insert(blocks, pandoc.HorizontalRule())
    table.insert(blocks, pandoc.Header(2, "Figures omitted"))
    table.insert(
        blocks,
        pandoc.Para(pandoc.Str(
            "The source document embedded " .. #dropped ..
            " figure(s). They are not reproduced here: this is a public repository " ..
            "and the figures are usually manufacturer artwork. Named for reference:"
        ))
    )
    local items = {}
    for _, d in ipairs(dropped) do
        table.insert(items, {pandoc.Plain(pandoc.Code(d))})
    end
    table.insert(blocks, pandoc.BulletList(items))
    return pandoc.Pandoc(blocks, doc.meta)
end
