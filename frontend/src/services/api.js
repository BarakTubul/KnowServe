// src/services/api.js
// In dev (no env var): falls back to '/api' and Vite proxy strips the prefix.
// In production (Vercel): set VITE_API_BASE_URL=https://your-backend.onrender.com
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api';

/**
 * Builds a WebSocket URL for the given path (e.g. /ws/documents/1).
 * In production, derives wss:// from VITE_API_BASE_URL.
 * In dev, routes through the Vite proxy using the current page host.
 */
export const getWsUrl = (path) => {
  if (import.meta.env.VITE_API_BASE_URL) {
    const wsBase = import.meta.env.VITE_API_BASE_URL
      .replace(/^https:\/\//, 'wss://')
      .replace(/^http:\/\//, 'ws://');
    return `${wsBase}${path}`;
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/api${path}`;
};

/**
 * Handles checking responses and throwing errors if bad response codes happen.
 */
const handleResponse = async (response, ignoreAuth = false) => {
    if (!response.ok) {
        if (response.status === 401 && !ignoreAuth) {
            window.dispatchEvent(new Event('auth:unauthorized'));
        }
        let errorData;
        try {
            errorData = await response.json();
        } catch (e) {
            throw new Error(`HTTP Error: ${response.status}`);
        }

        // Handle FastAPI Pydantic validation arrays
        let errorMessage = errorData.detail || 'An unknown server error occurred';
        if (Array.isArray(errorMessage)) {
            errorMessage = errorMessage.map(err => err.msg || JSON.stringify(err)).join(', ');
        }

        throw new Error(errorMessage);
    }
    const data = await response.json();
    console.log(`[API Response] ${response.url}:`, data);
    return data;
};

/**
 * Common configuration wrapper combining headers and auth cookies
 */
const getOptions = (method, body = null, isJSON = true) => {
    const headers = {};
    if (isJSON) {
        headers['Content-Type'] = 'application/json';
    }

    const options = {
        method,
        headers,
        credentials: 'include', // Crucial for sending HttpOnly cookies cross-origin (even proxied)
    };

    if (body) {
        options.body = isJSON ? JSON.stringify(body) : body;
    }

    return options;
};

// -- Auth API --
export const registerApi = async (data) => {
    const res = await fetch(`${API_BASE_URL}/auth/register`, getOptions('POST', data));
    return handleResponse(res);
};

export const loginApi = async (data) => {
    const res = await fetch(`${API_BASE_URL}/auth/login`, getOptions('POST', data));
    return handleResponse(res);
};

export const logoutApi = async () => {
    const res = await fetch(`${API_BASE_URL}/auth/logout`, getOptions('POST'));
    return handleResponse(res);
};

export const fetchMeApi = async () => {
    const res = await fetch(`${API_BASE_URL}/auth/me`, getOptions('GET'));
    return handleResponse(res, true);
};



// -- Documents API --
export const fetchAccessibleDocsApi = async () => {
    const res = await fetch(`${API_BASE_URL}/documents/my/access`, getOptions('GET'));
    return handleResponse(res);
};

// -- Admin Dashboard API --
export const fetchAdminDocsApi = async () => {
    const res = await fetch(`${API_BASE_URL}/admin/docs/`, getOptions('GET'));
    return handleResponse(res);
};

export const adminUploadApi = async (data) => {
    // Expected structure matches schemas.document_schema CreateDocumentDTO
    const res = await fetch(`${API_BASE_URL}/admin/docs/`, getOptions('POST', data));
    return handleResponse(res);
};

export const updateAdminDocAccessApi = async (docId, allowedDeptIds) => {
    const res = await fetch(`${API_BASE_URL}/admin/docs/${docId}/access`, getOptions('PATCH', { allowed_department_ids: allowedDeptIds }));
    return handleResponse(res);
};

export const deleteAdminDocApi = async (docId) => {
    const res = await fetch(`${API_BASE_URL}/admin/docs/${docId}`, getOptions('DELETE'));
    return handleResponse(res, false);
};

// -- Chat API --
export const fetchChatStreamResponse = async (messages, onChunk, onError, onComplete) => {
    try {
        console.log(`[API Request] /api/chat/stream payload:`, messages);
        const response = await fetch(`${API_BASE_URL}/chat/stream`, getOptions('POST', { messages }));

        if (!response.ok) {
            if (response.status === 401) {
                window.dispatchEvent(new Event('auth:unauthorized'));
            }
            throw new Error(`HTTP Error: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");

        while (true) {
            const { done, value } = await reader.read();
            if (done) {
                console.log(`[API Stream] Connection closed by server.`);
                if (onComplete) onComplete();
                break;
            }
            const chunk = decoder.decode(value, { stream: true });
            console.log(`[API Stream Raw Chunk]:`, chunk);

            // SSE parse
            const lines = chunk.split('\n');
            for (let line of lines) {
                if (line.startsWith('data: ')) {
                    const dataStr = line.replace('data: ', '').trim();
                    if (dataStr) {
                        try {
                            const dataObj = JSON.parse(dataStr);
                            console.log(`[API Stream Parsed JSON]:`, dataObj);
                            if (dataObj.type === 'token' && dataObj.content) {
                                onChunk(dataObj.content);
                            } else if (dataObj.type === 'tool') {
                                console.log(`[API Stream Tool Call]:`, dataObj.tool);
                            }
                        } catch (e) {
                            // Non-json literal data string
                            console.log(`[API Stream Literal String]:`, dataStr);
                            onChunk(dataStr);
                        }
                    }
                }
            }
        }
    } catch (err) {
        if (onError) onError(err);
    }
};
