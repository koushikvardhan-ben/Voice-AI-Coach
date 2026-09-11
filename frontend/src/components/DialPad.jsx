import { Phone, PhoneOff, Delete } from "lucide-react";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

export default function DialPad({ number, setNumber, onDial, onHangup, canDial, canHangup }) {
  return (
    <div>
      <input
        className="mb-3 w-full rounded-lg border border-outline-variant/30 bg-surface-container-low/70 px-4 py-3 text-center text-lg tracking-wide text-on-surface font-code-sm placeholder:text-on-surface-variant/40 focus:border-primary/60 focus:outline-none focus:ring-1 focus:ring-primary/40"
        type="tel"
        inputMode="tel"
        placeholder="+91 98765 43210"
        value={number}
        onChange={(e) => setNumber(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && canDial) onDial();
        }}
      />

      <div className="mb-4 grid grid-cols-3 gap-2">
        {KEYS.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setNumber((number || "") + k)}
            className="rounded-lg border border-outline-variant/20 bg-surface-container/50 py-3 text-lg text-on-surface transition hover:border-primary/30 hover:bg-surface-container-high active:scale-[0.97]"
          >
            {k}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={onDial}
          disabled={!canDial}
          className="btn-primary-glow flex items-center justify-center gap-2 rounded-lg bg-secondary py-3 font-semibold text-on-secondary disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Phone size={16} /> Call
        </button>
        <button
          type="button"
          onClick={onHangup}
          disabled={!canHangup}
          className="btn-danger-glow flex items-center justify-center gap-2 rounded-lg bg-error py-3 font-semibold text-on-error disabled:cursor-not-allowed disabled:opacity-40"
        >
          <PhoneOff size={16} /> Hang up
        </button>
      </div>

      {number ? (
        <button
          type="button"
          onClick={() => setNumber(number.slice(0, -1))}
          className="mt-3 flex items-center gap-1 text-xs text-on-surface-variant transition hover:text-on-surface"
        >
          <Delete size={13} /> Delete
        </button>
      ) : null}
    </div>
  );
}
