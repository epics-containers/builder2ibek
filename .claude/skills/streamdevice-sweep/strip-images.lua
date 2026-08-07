-- Drop every image from a pandoc document and record what was dropped.
--
-- ibek-runtime-streamdevice is a PUBLIC repo and DLS documentation folders
-- routinely embed manufacturer figures that DLS has no right to redistribute.
-- An honest gap beats a broken image link, so the figures are listed at the end
-- of the converted document instead of being copied.

local dropped = {}

local function note(src, alt)
    table.insert(dropped, alt ~= "" and (alt .. " (" .. src .. ")") or src)
end

function Image(el)
    local src = el.src or "?"
    local alt = pandoc.utils.stringify(el.caption or "")
    note(src, alt)
    return {}
end

-- An `<img>` written as HTML is NOT parsed into an Image: every reader keeps it
-- as RawInline/RawBlock, so Image() above never sees it and the figure survives
-- into the public repo. sweep-docs.py routes exactly these files here - MD_IMAGE
-- matches `<img` as well as `![](...)` - so missing them defeats the detour.
-- The tags are cut out of the raw text rather than the whole element dropped,
-- because a RawBlock is often a `<div>` wrapping prose that must survive.
local function strip_img_tags(text)
    local removed = 0
    -- The trailing blank is taken with the tag: a bare newline left inside a
    -- `<div>` comes back out of the gfm writer as a literal `&#10;`.
    local out = text:gsub("<([iI][mM][gG])([^>]*)>[ \t]*\n?", function(_, attrs)
        -- `<image>` and friends are not `<img>`: an attribute list has to start
        -- with a space or the tag has to end right there (`<img>`, `<img/>`).
        if attrs ~= "" and not attrs:match("^[%s/]") then
            return nil -- leave the match untouched
        end
        -- The leading %s is required, not decoration: without it `src` matches
        -- inside `data-src` and the figure list names the lazy-load
        -- placeholder instead of the real image. attrs always opens with the
        -- separator after `<img`, so a real attribute is always preceded by
        -- whitespace.
        local src = attrs:match("%s[sS][rR][cC]%s*=%s*[\"']([^\"']*)[\"']")
            or attrs:match("%s[sS][rR][cC]%s*=%s*([^%s>]+)")
            or "?"
        local alt = attrs:match("%s[aA][lL][tT]%s*=%s*[\"']([^\"']*)[\"']") or ""
        note(src, alt)
        removed = removed + 1
        return ""
    end)
    return out, removed
end

local function strip_raw(el, ctor)
    if not el.format:match("html") then
        return nil
    end
    local text, removed = strip_img_tags(el.text)
    if removed == 0 then
        return nil
    end
    if text:match("^%s*$") then
        return {}
    end
    return ctor(el.format, text)
end

function RawInline(el)
    return strip_raw(el, pandoc.RawInline)
end

function RawBlock(el)
    return strip_raw(el, pandoc.RawBlock)
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
