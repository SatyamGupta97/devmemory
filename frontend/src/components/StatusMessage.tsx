interface Props {
  tone: "error" | "success" | "info";
  children: React.ReactNode;
  onDismiss?: () => void;
}

/**
 * One place that renders a message, so every failure looks the same and is
 * announced to screen readers (role="status" for success, "alert" for errors).
 */
export function StatusMessage({ tone, children, onDismiss }: Props) {
  return (
    <div className={`status status-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <span className="status-text">{children}</span>
      {onDismiss && (
        <button
          type="button"
          className="status-dismiss"
          onClick={onDismiss}
          aria-label="Dismiss message"
        >
          &times;
        </button>
      )}
    </div>
  );
}
