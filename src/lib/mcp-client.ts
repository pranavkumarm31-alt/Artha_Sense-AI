const MCP_URL = "https://mcp.mospi.gov.in/";
const PROTOCOL_VERSION = "2025-03-26";
const REQUEST_TIMEOUT_MS = 30_000;

interface MCPToolCallParams {
  name: string;
  arguments: Record<string, unknown>;
}

interface MCPResult {
  structuredContent?: Record<string, unknown>;
  content?: Array<{ type: string; text?: string }>;
  isError?: boolean;
}

interface MCPResponse {
  result?: Record<string, unknown>;
  sessionId: string;
}

// Extract MCP responses from SSE format.
function parseSSEResponse(raw: string): Record<string, unknown> {
  const blocks = raw.split(/\r?\n\r?\n/);
  let lastResult: Record<string, unknown> | undefined;

  for (const block of blocks) {
    const dataLines = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim());

    if (dataLines.length === 0) continue;

    const data = dataLines.join("\n");
    if (data === "[DONE]") continue;

    const message = JSON.parse(data);

    if (message.error) {
      throw new Error(`MCP error: ${message.error.message ?? JSON.stringify(message.error)}`);
    }

    if (message.result) {
      lastResult = message.result;
    }
  }

  if (!lastResult) {
    throw new Error(`No valid MCP result found in SSE response: ${raw.slice(0, 500)}`);
  }

  return lastResult;
}

// Support both JSON and SSE MCP responses.
function parseMCPResponse(raw: string, contentType: string): Record<string, unknown> {
  if (contentType.includes("text/event-stream")) {
    return parseSSEResponse(raw);
  }

  try {
    const message = JSON.parse(raw);

    if (message.error) {
      throw new Error(`MCP error: ${message.error.message ?? JSON.stringify(message.error)}`);
    }

    return message.result ?? message;
  } catch (error) {
    if (error instanceof SyntaxError) {
      return parseSSEResponse(raw);
    }
    throw error;
  }
}

// Send an MCP JSON-RPC request.
async function mcpFetch(body: Record<string, unknown>, sessionId?: string): Promise<MCPResponse> {
  const headers: Record<string, string> = {
    Accept: "application/json, text/event-stream",
    "Content-Type": "application/json",
  };

  if (sessionId) {
    headers["mcp-session-id"] = sessionId;
  }

  if (body.method !== "initialize") {
    headers["MCP-Protocol-Version"] = PROTOCOL_VERSION;
  }

  const response = await fetch(MCP_URL, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    cache: "no-store",
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });

  const newSessionId = response.headers.get("mcp-session-id") ?? sessionId ?? "";

  const raw = await response.text();

  if (!response.ok) {
    throw new Error(`MCP HTTP ${response.status}: ${raw || response.statusText}`);
  }

  // MCP notifications normally return HTTP 202 without a response body.
  if (response.status === 202 || response.status === 204 || !raw.trim()) {
    return {
      result: undefined,
      sessionId: newSessionId,
    };
  }

  return {
    result: parseMCPResponse(raw, response.headers.get("content-type") ?? ""),
    sessionId: newSessionId,
  };
}

// Initialize MCP session.
export async function initSession(): Promise<string> {
  const { result, sessionId } = await mcpFetch({
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: {
        name: "india-economic-dashboard",
        version: "1.0.0",
      },
    },
  });

  if (!result) {
    throw new Error("MCP initialization returned an empty response");
  }

  console.log("MCP initialized:", result.serverInfo ?? result);

  // Complete the MCP initialization handshake.
  await mcpFetch(
    {
      jsonrpc: "2.0",
      method: "notifications/initialized",
    },
    sessionId
  );

  console.log("MCP initialization handshake completed");

  return sessionId;
}

// Call an MCP tool.
export async function callTool(
  sessionId: string,
  params: MCPToolCallParams,
  requestId = 2
): Promise<MCPResult> {
  const { result } = await mcpFetch(
    {
      jsonrpc: "2.0",
      id: requestId,
      method: "tools/call",
      params: {
        name: params.name,
        arguments: params.arguments,
      },
    },
    sessionId
  );

  if (!result) {
    throw new Error(`Empty response from MCP tool: ${params.name}`);
  }

  const toolResult = result as MCPResult;

  if (toolResult.isError) {
    const errorText = toolResult.content?.[0]?.text ?? "Unknown MCP tool error";

    throw new Error(`MCP tool error (${params.name}): ${errorText}`);
  }

  return toolResult;
}

// Extract data from MCP tool response.
export function extractData<T>(result: MCPResult): T {
  const error = result.structuredContent?.error;
  if (error !== undefined) {
    throw new Error(
      `MoSPI returned an error: ${typeof error === "string" ? error : JSON.stringify(error)}`
    );
  }

  const structuredData = result.structuredContent?.data;

  if (structuredData !== undefined) {
    return structuredData as T;
  }

  const text = result.content?.find((item) => item.type === "text" && item.text)?.text;

  if (text) {
    const parsed = JSON.parse(text);

    if (parsed && typeof parsed === "object") {
      if ("error" in parsed) {
        const errorMessage =
          typeof parsed.error === "string" ? parsed.error : JSON.stringify(parsed.error);
        throw new Error(`MoSPI returned an error: ${errorMessage}`);
      }

      if ("data" in parsed) {
        return parsed.data as T;
      }
    }

    return parsed as T;
  }

  throw new Error("No data found in MCP response");
}
