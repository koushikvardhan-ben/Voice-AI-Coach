import { useCallback, useEffect, useRef, useState } from "react";
import { Device } from "@twilio/voice-sdk";
import { api, fetchToken, WS_BASE } from "../lib/api";
import { practiceTurns, practiceCoach, practiceSummary } from "../lib/practice";
import { mergeCallStatus, upsertTurn, mergeCoach, mergeCoachStatus } from "../lib/callEvents";
import { voiceDeviceOptions, voiceError, watchCallConnection } from "../lib/voiceConnection";

export function useCall() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState("idle");
  const [turns, setTurns] = useState([]);
  const [interim, setInterim] = useState({});
  const [transcription, setTranscription] = useState({});
  const [coach, setCoach] = useState(null);
  const [coachStatus, setCoachStatus] = useState(null);
  const [summary, setSummary] = useState(null);
  const [notice, setNotice] = useState(null);
  const [muted, setMuted] = useState(false);
  const [isDemo, setIsDemo] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [connectedAt, setConnectedAt] = useState(null);
  const [retry, setRetry] = useState(0);
  const refs = useRef({ device: null, call: null, ws: null, timer: null, recovery: null, reconnectTimer: null, socketTimeout: null, active: false, demo: false, count: 0, callId: null, mounted: true, recovered: false });
  const r = refs.current;

  useEffect(() => {
    let cancelled = false;
    r.mounted = true;
    setReady(false);
    (async () => {
      try {
        const { token } = await fetchToken();
        if (cancelled) return;
        const device = new Device(token, voiceDeviceOptions);
        device.on("error", e => { if (!cancelled) setError(voiceError(e)); });
        device.on("tokenWillExpire", async () => {
          try { const fresh = await fetchToken(); if (!cancelled) device.updateToken(fresh.token); }
          catch (e) { if (!cancelled) { setReady(false); setError(e.message); } }
        });
        r.device = device;
        setReady(true);
        setError(null);
      } catch (e) { if (!cancelled) setError(e.message); }
    })();
    return () => { cancelled = true; r.device?.destroy(); r.device = null; };
  }, [retry]);

  useEffect(() => () => {
    r.mounted = false;
    clearInterval(r.timer);
    clearInterval(r.recovery);
    clearTimeout(r.reconnectTimer); clearTimeout(r.socketTimeout);
    r.ws?.close();
  }, []);

  const recoverSummary = useCallback(() => {
    if (r.recovery || r.demo || r.recovered || !r.callId) return;
    let attempts = 0;
    const callId = r.callId;
    setFinalizing(true);
    r.recovery = setInterval(async () => {
      if (callId !== r.callId || !r.mounted) return;
      try {
        const saved = await api(`/api/calls/${callId}`);
        if (callId !== r.callId || !r.mounted) return;
        setSummary(saved.summary);
        setTurns(saved.transcript);
        r.recovered = true;
        clearInterval(r.recovery); r.recovery = null;
        setFinalizing(false); r.active = false; r.ws?.close();
      } catch {
        if (++attempts >= 15 && r.mounted) {
          clearInterval(r.recovery); r.recovery = null;
          setFinalizing(false); r.active = false;
          setNotice("The summary has not arrived. Check Call history after the backend finishes processing.");
        }
      }
    }, 3000);
  }, []);

  const finish = useCallback((failed = false) => {
    if (!r.mounted) return;
    setStatus(s => failed || s === "failed" ? "failed" : "ended");
    setInterim({}); setMuted(false);
    if (!r.demo) recoverSummary();
  }, [recoverSummary]);

  const handleEvent = useCallback(evt => {
    if (!r.mounted) return;
    if (evt.type === "status" && evt.status !== "idle") {
      setStatus(s => mergeCallStatus(s, evt.status));
      if (evt.status === "connected") setConnectedAt(t => t || Date.now());
      if (["ended", "failed"].includes(evt.status)) finish(evt.status === "failed");
    }
    if (evt.type === "transcript" && evt.turn) {
      const t = evt.turn;
      if (t.is_final) {
        setTurns(prev => upsertTurn(prev, t));
        setInterim(prev => { const next = { ...prev }; delete next[t.speaker]; return next; });
      } else setInterim(prev => ({ ...prev, [t.speaker]: t.text }));
    }
    if (evt.type === "coach") setCoach(previous => mergeCoach(previous, evt.coach));
    if (evt.type === "coach_status") setCoachStatus(previous => mergeCoachStatus(previous, evt));
    if (evt.type === "stt_status") setTranscription(prev => ({ ...prev, [evt.speaker]: evt }));
    if (evt.type === "notice") setNotice(evt.message);
    if (evt.type === "summary") {
      setSummary(evt.summary); setFinalizing(false); r.active = false; r.recovered = true;
      clearInterval(r.recovery); r.recovery = null;
    }
  }, [finish]);

  const reset = useCallback(demo => {
    clearInterval(r.timer); clearInterval(r.recovery); r.recovery = null;
    clearTimeout(r.reconnectTimer); clearTimeout(r.socketTimeout);
    if (r.ws) { r.ws.onclose = null; r.ws.close(); r.ws = null; }
    r.active = true; r.demo = demo; r.recovered = false; r.count = 0; r.call = null; r.callId = null;
    r.localHangup = false; r.sdkEvents = [];
    setTurns([]); setInterim({}); setTranscription({}); setCoach(null); setSummary(null); setNotice(null);
    setCoachStatus(null);
    setMuted(false); setIsDemo(demo); setConnectedAt(null); setFinalizing(false);
  }, []);

  const dial = useCallback(async (number, agentId) => {
    if (r.active) return;
    const to = number.replace(/[\s()-]/g, "");
    if (!/^\+[1-9]\d{7,14}$/.test(to)) { setError("Enter a phone number with country code, for example +919876543210."); return; }
    if (!r.device || !ready) { setError("Calling is not ready. Check the service settings, then reconnect."); return; }
    reset(false); setError(null); setStatus("dialing");
    const callId = crypto.randomUUID(); r.callId = callId;
    try {
      const ws = new WebSocket(`${WS_BASE}/ws/${callId}`); r.ws = ws;
      ws.onmessage = e => { if (callId !== r.callId) return; try { handleEvent(JSON.parse(e.data)); } catch { setNotice("A live update could not be read."); } };
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error("The live transcript connection timed out.")), 8000);
        ws.onopen = () => { clearTimeout(timeout); resolve(); };
        ws.onerror = () => { clearTimeout(timeout); reject(new Error("Cannot open the live transcript connection.")); };
        ws.onclose = () => { clearTimeout(timeout); reject(new Error("The live connection closed before dialing.")); };
      });
      if (!r.active) { ws.close(); return; }
      let reconnects = 0;
      const scheduleReconnect = () => {
        clearTimeout(r.socketTimeout);
        if (!r.mounted || !r.active || r.recovered || r.callId !== callId) return;
        if (reconnects >= 5) {
          setNotice("Live updates could not reconnect. You can still end the call; check Call history for the saved transcript.");
          return;
        }
        setNotice("Reconnecting live updates… Your phone call can continue.");
        clearTimeout(r.reconnectTimer);
        r.reconnectTimer = setTimeout(() => {
          if (!r.mounted || !r.active || r.recovered || r.callId !== callId) return;
          const next = new WebSocket(`${WS_BASE}/ws/${callId}`);
          r.ws = next;
          r.socketTimeout = setTimeout(() => next.close(), 5000);
          next.onmessage = ws.onmessage;
          next.onopen = () => {
            clearTimeout(r.socketTimeout);
            for (const event of r.sdkEvents.splice(0)) next.send(JSON.stringify(event));
            setNotice("Live updates reconnected.");
          };
          next.onclose = scheduleReconnect;
          next.onerror = () => next.close();
        }, Math.min(300 * 2 ** reconnects++, 3000));
      };
      ws.onclose = scheduleReconnect;
      const call = await r.device.connect({ params: { PhoneNumber: to, CallId: callId, AgentId: agentId || "" } });
      r.call = call;
      if (!r.active) { call.disconnect(); return; }
      let awaitingBridge = false;
      call.on("ringing", hasEarlyMedia => {
        awaitingBridge = hasEarlyMedia === false;
        setStatus(s => mergeCallStatus(s, "ringing"));
      });
      // With answerOnBridge=true, a no-early-media ringing -> accept transition
      // signals the bridge opening. Trial announcements/early media do NOT count.
      // Customer-leg callbacks remain the fallback and the server's authority.
      call.on("accept", () => {
        if (awaitingBridge) {
          setStatus(s => mergeCallStatus(s, "connected"));
          setConnectedAt(t => t || Date.now());
        }
      });
      watchCallConnection(call, {
        report: (event, e = {}, closed = false) => {
          if (callId !== r.callId) return;
          const payload = { type: "sdk_event", event, code: e.code, closed };
          if (r.ws?.readyState === WebSocket.OPEN) r.ws.send(JSON.stringify(payload));
          else r.sdkEvents = [...r.sdkEvents.slice(-19), payload];
        },
        notice: message => { if (callId === r.callId) setNotice(message); },
        error: message => { if (callId === r.callId) setError(message); },
        finish: failed => {
          if (callId !== r.callId) return;
          if (!r.localHangup) setNotice("The phone connection ended. Any Twilio error is shown above; connection events are saved with this call.");
          finish(failed);
        },
      });
    } catch (e) {
      setError(e.message); setStatus("failed"); r.active = false; r.ws?.close();
    }
  }, [ready, reset, handleEvent, finish]);

  const finishPractice = useCallback(() => {
    clearInterval(r.timer); r.active = false;
    setStatus("ended"); setInterim({});
    setSummary(r.count === practiceTurns.length ? practiceSummary : {
      outcome: "unclear", key_points: ["Practice ended early. Review the displayed sample transcript."], objections: [], commitments: [], next_steps: ["Replay the walkthrough to see the complete coaching flow."],
    });
  }, []);

  const practice = useCallback(() => {
    if (r.active) return;
    reset(true); setStatus("connected"); setConnectedAt(Date.now());
    r.timer = setInterval(() => {
      if (r.count >= practiceTurns.length) { finishPractice(); return; }
      const i = r.count++;
      const [speaker, text] = practiceTurns[i];
      setTurns(prev => [...prev, { id: `sample-${i}`, seq: i, speaker, text, is_final: true, ts: Date.now() / 1000 }]);
      setCoach({ ...practiceCoach[i], customer_role: "buyer", updated_at: Date.now() / 1000 });
    }, 2600);
  }, [reset, finishPractice]);

  const hangup = useCallback(() => {
    if (r.demo) { finishPractice(); return; }
    r.localHangup = true;
    if (r.ws?.readyState === WebSocket.OPEN) r.ws.send(JSON.stringify({ type: "sdk_event", event: "local_hangup" }));
    const pending = !r.call;
    try { r.call?.disconnect(); r.device?.disconnectAll(); } catch { /* call already ended */ }
    if (pending) r.active = false;
    finish();
  }, [finish, finishPractice]);
  const toggleMute = () => {
    if (!r.call || r.demo) return;
    const next = !r.call.isMuted(); r.call.mute(next); setMuted(next);
  };
  return { ready, error, status, turns, interim, transcription, coach, coachStatus, summary, notice, muted, isDemo, finalizing, connectedAt,
    dial, hangup, practice, toggleMute, reconnect: () => {
      if (r.active) { setNotice("End the current call before reconnecting the calling device."); return; }
      setRetry(n => n + 1);
    } };
}
