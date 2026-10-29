/** Generic four-pane window mark for Windows-only settings; plain geometry in currentColor, no third-party artwork. */
export function WindowsIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">
      <path d="M3 5.4 10.6 4.3v6.8H3z" />
      <path d="M12 4.1 21 2.8v8.3h-9z" />
      <path d="M3 12.6h7.6v6.9L3 18.4z" />
      <path d="M12 12.6h9v8.6l-9-1.3z" />
    </svg>
  )
}
