"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

interface Citation {
  id: string;
  kind: "observation" | "forecast" | "analysis" | "anomaly" | "document";
  title: string;
  content: string;
  source_name: string;
  source_url: string;
  observation_period: string | null;
  publication_date: string | null;
  metadata: Record<string, unknown>;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  created_at?: string;
}

interface Conversation {
  id: string;
  title: string;
  messages: Message[];
}

const suggestedQuestions = [
  "What is India's latest GDP growth?",
  "Compare CPI and WPI inflation",
  "Explain the latest IIP trend",
  "Which indicators show unusual movements?",
  "Compare the latest forecasts across models",
];

export function ResearchAssistant() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    fetch("/api/research/history", { cache: "no-store" })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok || payload.error) throw new Error(payload.error ?? "History unavailable.");
        if (!active) return;
        const items = payload as Conversation[];
        setConversations(items);
        if (items.length) {
          setConversationId(items[0].id);
          setMessages(items[0].messages);
        }
      })
      .catch((requestError) => {
        if (active) {
          setError(requestError instanceof Error ? requestError.message : "History unavailable.");
        }
      })
      .finally(() => {
        if (active) setLoadingHistory(false);
      });
    return () => {
      active = false;
    };
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: Scroll after message or loading state changes.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  const startNewConversation = () => {
    setConversationId(null);
    setMessages([]);
    setQuestion("");
    setError(null);
  };

  const sendQuestion = async (event?: FormEvent, suggested?: string) => {
    event?.preventDefault();
    const text = (suggested ?? question).trim();
    if (!text || sending) return;
    setSending(true);
    setError(null);
    setMessages((current) => [...current, { role: "user", content: text, citations: [] }]);
    setQuestion("");
    try {
      const response = await fetch("/api/research/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text, conversation_id: conversationId }),
        cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok || payload.error)
        throw new Error(payload.error ?? "Research request failed.");
      const answer = payload as {
        conversation_id: string;
        answer: string;
        citations: Citation[];
      };
      setConversationId(answer.conversation_id);
      setMessages((current) => [
        ...current,
        { role: "assistant", content: answer.answer, citations: answer.citations },
      ]);
      setConversations((current) => {
        const existing = current.find((item) => item.id === answer.conversation_id);
        const updated = existing
          ? {
              ...existing,
              messages: [
                ...existing.messages,
                { role: "user" as const, content: text, citations: [] },
                { role: "assistant" as const, content: answer.answer, citations: answer.citations },
              ],
            }
          : {
              id: answer.conversation_id,
              title: text.slice(0, 120),
              messages: [
                { role: "user" as const, content: text, citations: [] },
                { role: "assistant" as const, content: answer.answer, citations: answer.citations },
              ],
            };
        return [updated, ...current.filter((item) => item.id !== answer.conversation_id)];
      });
    } catch (requestError) {
      setMessages((current) => current.slice(0, -1));
      setQuestion(text);
      setError(
        requestError instanceof Error ? requestError.message : "Research service unavailable."
      );
    } finally {
      setSending(false);
    }
  };

  const selectConversation = (conversation: Conversation) => {
    setConversationId(conversation.id);
    setMessages(conversation.messages);
    setError(null);
  };

  return (
    <div className="grid min-h-[620px] gap-5 lg:grid-cols-[250px_minmax(0,1fr)]">
      <aside className="rounded-2xl border border-slate-200 bg-white/80 p-4 dark:border-slate-700 dark:bg-slate-900/70">
        <button
          type="button"
          onClick={startNewConversation}
          className="w-full rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-700 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-200"
        >
          + New conversation
        </button>
        <h2 className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Recent conversations
        </h2>
        {loadingHistory ? (
          <p className="py-3 text-sm text-slate-500">Loading history…</p>
        ) : conversations.length ? (
          <div className="space-y-1">
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                onClick={() => selectConversation(conversation)}
                className={`w-full truncate rounded-lg px-3 py-2 text-left text-sm ${
                  conversation.id === conversationId
                    ? "bg-amber-50 font-medium text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                {conversation.title}
              </button>
            ))}
          </div>
        ) : (
          <p className="py-3 text-sm text-slate-500">Your conversations will appear here.</p>
        )}
        <p className="mt-6 border-t border-slate-200 pt-4 text-xs leading-relaxed text-slate-500 dark:border-slate-700">
          This browser session uses a private, HttpOnly identifier. There is no account sign-in in
          this dashboard; clearing site data starts a new research history.
        </p>
      </aside>

      <section className="flex min-h-[620px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white/80 dark:border-slate-700 dark:bg-slate-900/70">
        <header className="border-b border-slate-200 px-5 py-4 dark:border-slate-700">
          <h2 className="font-semibold text-slate-900 dark:text-white">
            AI Economic Research Assistant
          </h2>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Answers use persisted observations and cited official publications. Forecasts are
            labeled separately from actuals.
          </p>
        </header>

        <div className="flex-1 space-y-5 overflow-y-auto p-4 sm:p-6">
          {messages.length === 0 && (
            <div className="mx-auto max-w-2xl py-8 text-center">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300">
                <svg
                  viewBox="0 0 24 24"
                  className="h-6 w-6"
                  fill="none"
                  stroke="currentColor"
                  aria-hidden="true"
                >
                  <path
                    d="M12 3v2m0 14v2M5.64 5.64l1.42 1.42m9.88 9.88 1.42 1.42M3 12h2m14 0h2M5.64 18.36l1.42-1.42m9.88-9.88 1.42-1.42M8 12a4 4 0 1 0 8 0 4 4 0 0 0-8 0Z"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                </svg>
              </div>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                Research with evidence, not guesses
              </h3>
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                Ask about observed indicators, saved forecasts, analysis, anomalies or ingested
                official reports.
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {suggestedQuestions.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    disabled={sending}
                    onClick={() => void sendQuestion(undefined, suggestion)}
                    className="rounded-full border border-slate-200 px-3 py-2 text-xs text-slate-700 transition hover:border-amber-300 hover:bg-amber-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((message, index) => (
            <article
              key={`${index}-${message.role}`}
              className={message.role === "user" ? "ml-auto max-w-3xl" : "mr-auto max-w-4xl"}
            >
              <div
                className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                  message.role === "user"
                    ? "bg-slate-900 text-white dark:bg-slate-700"
                    : "border border-slate-200 bg-white text-slate-800 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
                }`}
              >
                <p className="whitespace-pre-wrap">{message.content}</p>
              </div>
              {message.role === "assistant" && message.citations.length > 0 && (
                <details className="mt-2 rounded-xl border border-slate-200 bg-slate-50/80 p-3 dark:border-slate-700 dark:bg-slate-800/50">
                  <summary className="cursor-pointer text-xs font-semibold text-slate-600 dark:text-slate-300">
                    Evidence & sources ({message.citations.length})
                  </summary>
                  <div className="mt-3 space-y-2">
                    {message.citations.map((citation) => (
                      <div
                        key={citation.id}
                        className="rounded-lg bg-white p-3 text-xs dark:bg-slate-900"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-semibold text-slate-800 dark:text-slate-100">
                            [{String(citation.metadata.citation_id ?? "")}] {citation.title}
                          </span>
                          {citation.observation_period && (
                            <span className="text-slate-500">{citation.observation_period}</span>
                          )}
                        </div>
                        <p className="mt-1 leading-relaxed text-slate-600 dark:text-slate-300">
                          {citation.content}
                        </p>
                        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-slate-500">
                          <span>{citation.source_name}</span>
                          {citation.publication_date && (
                            <span>
                              Published/observed{" "}
                              {new Date(citation.publication_date).toLocaleDateString("en-IN")}
                            </span>
                          )}
                          {citation.source_url && (
                            <a
                              href={citation.source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="font-medium text-blue-700 underline dark:text-blue-300"
                            >
                              Open source
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </article>
          ))}
          {sending && (
            <output className="mr-auto flex items-center gap-2 rounded-xl bg-slate-100 px-4 py-3 text-sm text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              <span className="h-2 w-2 animate-pulse rounded-full bg-amber-500" />
              Retrieving evidence and preparing a cited response…
            </output>
          )}
          <div ref={bottomRef} />
        </div>

        {error && (
          <div
            role="alert"
            className="mx-4 mb-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200"
          >
            {error}
          </div>
        )}

        <form
          onSubmit={(event) => void sendQuestion(event)}
          className="border-t border-slate-200 p-3 sm:p-4 dark:border-slate-700"
        >
          <label htmlFor="research-question" className="sr-only">
            Ask an economic research question
          </label>
          <div className="flex items-end gap-2">
            <textarea
              id="research-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendQuestion();
                }
              }}
              maxLength={4000}
              rows={2}
              placeholder="Ask about India's economic data…"
              className="min-h-12 flex-1 resize-y rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-amber-500 focus:ring-2 focus:ring-amber-200 dark:border-slate-600 dark:bg-slate-950 dark:text-white dark:focus:ring-amber-900"
            />
            <button
              type="submit"
              disabled={sending || !question.trim()}
              className="rounded-xl bg-amber-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Send
            </button>
          </div>
          <p className="mt-2 px-1 text-[11px] text-slate-500">
            Numerical claims are checked against retrieved evidence. Statistical relationships do
            not establish causation.
          </p>
        </form>
      </section>
    </div>
  );
}
