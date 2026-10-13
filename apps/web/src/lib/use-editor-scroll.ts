import { useCallback, useRef } from "react";

export function useEditorScroll<T extends HTMLElement>() {
  const editorRef = useRef<T>(null);

  const scrollToEditor = useCallback(() => {
    window.requestAnimationFrame(() => {
      const editor = editorRef.current;
      if (!editor) return;

      const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      editor.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
      editor.querySelector<HTMLElement>("[data-editor-heading]")?.focus({ preventScroll: true });
    });
  }, []);

  return { editorRef, scrollToEditor };
}
