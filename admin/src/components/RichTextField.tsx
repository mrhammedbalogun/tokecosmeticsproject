"use client";

/**
 * A rich text form field backed by TipTap, for the product HTML fields.
 *
 * ── WHY THE VALUE IS STILL AN HTML STRING ───────────────────────────────────────────
 *
 * The form state (`ProductFormValues`), the PATCH payload and the database column all
 * hold HTML strings, exactly as the plain textareas did. This component is a drop-in
 * replacement at the same boundary: `value` in, `onChange(html)` out. Nothing upstream
 * of the panel changed shape, and `isDirty` keeps comparing strings.
 *
 * ── THE TOOLBAR MATCHES THE SERVER'S ALLOW-LIST ─────────────────────────────────────
 *
 * The backend sanitises these fields on write through `apps/cms/sanitize.py` (nh3):
 * h2–h4, bold/italic/underline/strike, lists, blockquote, links. The toolbar offers
 * exactly that vocabulary and nothing more, so what an author sees in the editor is what
 * the storefront renders — no button whose effect the sanitiser would silently undo.
 *
 * ── EMPTY IS "" ─────────────────────────────────────────────────────────────────────
 *
 * TipTap's empty document serialises as `<p></p>`. Normalised to `""` on the way out,
 * because the storefront hides an accordion section on falsy content and `isDirty` must
 * not arm the Save button over a field nobody touched.
 */
import { useEffect } from "react";
import { EditorContent, useEditor, useEditorState } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Placeholder } from "@tiptap/extensions";

type Level = 2 | 3 | 4;

function ToolButton({
  title,
  active,
  disabled,
  onClick,
  children,
}: {
  title: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      aria-pressed={active}
      disabled={disabled}
      // Keeps focus (and the selection the command applies to) in the editor.
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      className={`min-w-7 rounded px-1.5 py-1 text-xs leading-none disabled:opacity-40 ${
        active ? "bg-accent/10 font-semibold text-accent" : "text-muted hover:text-fg"
      }`}
    >
      {children}
    </button>
  );
}

export function RichTextField({
  label,
  value,
  onChange,
  placeholder,
  error,
  rows = 6,
}: {
  label: string;
  value: string;
  onChange: (html: string) => void;
  placeholder?: string;
  error?: string;
  /** Approximate visible height, in textarea-row terms — the panels already think in rows. */
  rows?: number;
}) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3, 4] },
        // Clicking a link in a form field must edit it, not leave the admin.
        link: { openOnClick: false },
      }),
      Placeholder.configure({ placeholder: placeholder ?? "" }),
    ],
    content: value,
    // The admin server-renders this page; TipTap must not render until the client, or
    // the hydration pass sees a document the server never produced.
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class: "rich-text focus:outline-none",
        style: `min-height: ${rows * 1.6}em`,
      },
    },
    onUpdate: ({ editor }) => onChange(editor.isEmpty ? "" : editor.getHTML()),
  });

  // Adopt EXTERNAL changes to `value` (a reset, a server-normalised save) without
  // touching the caret while typing: after our own onUpdate round-trips through the
  // parent, `value` equals what the editor already holds and this does nothing.
  useEffect(() => {
    if (!editor) return;
    const current = editor.isEmpty ? "" : editor.getHTML();
    if (value !== current) {
      editor.commands.setContent(value, { emitUpdate: false });
    }
  }, [editor, value]);

  // v3 editors do not re-render React on every transaction; the toolbar's active states
  // are subscribed explicitly instead.
  const state = useEditorState({
    editor,
    selector: ({ editor: e }) =>
      e
        ? {
            bold: e.isActive("bold"),
            italic: e.isActive("italic"),
            underline: e.isActive("underline"),
            strike: e.isActive("strike"),
            bulletList: e.isActive("bulletList"),
            orderedList: e.isActive("orderedList"),
            blockquote: e.isActive("blockquote"),
            link: e.isActive("link"),
            block: e.isActive("heading", { level: 2 })
              ? "2"
              : e.isActive("heading", { level: 3 })
                ? "3"
                : e.isActive("heading", { level: 4 })
                  ? "4"
                  : "p",
            canUndo: e.can().undo(),
            canRedo: e.can().redo(),
          }
        : null,
  });

  const setBlock = (block: string) => {
    if (!editor) return;
    const chain = editor.chain().focus();
    if (block === "p") chain.setParagraph().run();
    else chain.setHeading({ level: Number(block) as Level }).run();
  };

  const editLink = () => {
    if (!editor) return;
    const previous = (editor.getAttributes("link").href as string | undefined) ?? "";
    // window.prompt is deliberate: a one-field ask in a staff tool does not need a
    // popover, and a popover needs positioning, focus management and a dismiss story.
    const url = window.prompt("Link URL (leave empty to remove the link)", previous || "https://");
    if (url === null) return;
    const trimmed = url.trim();
    if (!trimmed) {
      editor.chain().focus().extendMarkRange("link").unsetLink().run();
    } else {
      editor.chain().focus().extendMarkRange("link").setLink({ href: trimmed }).run();
    }
  };

  return (
    <div className="block text-xs text-muted">
      {label}
      <div className="mt-1 rounded border border-line bg-surface focus-within:border-accent">
        <div className="flex flex-wrap items-center gap-0.5 border-b border-line px-1 py-1">
          <select
            aria-label={`${label} text style`}
            value={state?.block ?? "p"}
            onChange={(e) => setBlock(e.target.value)}
            disabled={!editor}
            className="rounded border border-line bg-surface px-1 py-0.5 text-xs focus:border-accent focus:outline-none"
          >
            <option value="p">Paragraph</option>
            <option value="2">Heading — large</option>
            <option value="3">Heading — medium</option>
            <option value="4">Heading — small</option>
          </select>

          <span aria-hidden className="mx-1 h-4 w-px bg-line" />

          <ToolButton
            title="Bold"
            active={state?.bold}
            disabled={!editor}
            onClick={() => editor?.chain().focus().toggleBold().run()}
          >
            <span className="font-bold">B</span>
          </ToolButton>
          <ToolButton
            title="Italic"
            active={state?.italic}
            disabled={!editor}
            onClick={() => editor?.chain().focus().toggleItalic().run()}
          >
            <span className="italic">I</span>
          </ToolButton>
          <ToolButton
            title="Underline"
            active={state?.underline}
            disabled={!editor}
            onClick={() => editor?.chain().focus().toggleUnderline().run()}
          >
            <span className="underline">U</span>
          </ToolButton>
          <ToolButton
            title="Strikethrough"
            active={state?.strike}
            disabled={!editor}
            onClick={() => editor?.chain().focus().toggleStrike().run()}
          >
            <span className="line-through">S</span>
          </ToolButton>

          <span aria-hidden className="mx-1 h-4 w-px bg-line" />

          <ToolButton
            title="Bullet list"
            active={state?.bulletList}
            disabled={!editor}
            onClick={() => editor?.chain().focus().toggleBulletList().run()}
          >
            • List
          </ToolButton>
          <ToolButton
            title="Numbered list"
            active={state?.orderedList}
            disabled={!editor}
            onClick={() => editor?.chain().focus().toggleOrderedList().run()}
          >
            1. List
          </ToolButton>
          <ToolButton
            title="Quote"
            active={state?.blockquote}
            disabled={!editor}
            onClick={() => editor?.chain().focus().toggleBlockquote().run()}
          >
            ❝
          </ToolButton>
          <ToolButton title="Link" active={state?.link} disabled={!editor} onClick={editLink}>
            Link
          </ToolButton>

          <span aria-hidden className="mx-1 h-4 w-px bg-line" />

          <ToolButton
            title="Clear formatting"
            disabled={!editor}
            onClick={() => editor?.chain().focus().clearNodes().unsetAllMarks().run()}
          >
            Clear
          </ToolButton>
          <ToolButton
            title="Undo"
            disabled={!editor || !state?.canUndo}
            onClick={() => editor?.chain().focus().undo().run()}
          >
            ↺
          </ToolButton>
          <ToolButton
            title="Redo"
            disabled={!editor || !state?.canRedo}
            onClick={() => editor?.chain().focus().redo().run()}
          >
            ↻
          </ToolButton>
        </div>

        <EditorContent editor={editor} aria-label={label} />
      </div>
      {error && <p className="mt-1 text-xs text-warn">{error}</p>}
    </div>
  );
}
