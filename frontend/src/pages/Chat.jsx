import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { fetchChatStreamResponse } from '../services/api';
import { useChatContext } from '../context/ChatContext';
import './Chat.css';

const Chat = () => {
    const { messages, setMessages } = useChatContext();
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const messagesEndRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages, isLoading]);

    const handleSend = async (e) => {
        e.preventDefault();
        if (!input.trim()) return;

        const userMessage = { id: Date.now(), sender: 'user', text: input };
        setMessages((prev) => [...prev, userMessage]);
        setInput('');
        setIsLoading(true);

        const aiMessageId = Date.now() + 1;
        setMessages((prev) => [...prev, { id: aiMessageId, sender: 'system', text: '' }]);

        // Build Payload (send max last 20 messages to conserve network bandwidth)
        const MAX_NETWORK_MESSAGES = 20;
        const allMessages = [...messages.filter(m => m.id !== 1), userMessage];
        const apiMessages = allMessages.slice(-MAX_NETWORK_MESSAGES).map(m => ({
            role: m.sender === 'user' ? 'user' : 'assistant',
            content: m.text
        }));

        await fetchChatStreamResponse(
            apiMessages,
            (chunk) => {
                console.log(`[Chat UI] Appending chunk to message state:`, chunk);
                setMessages((prev) =>
                    prev.map((msg) =>
                        msg.id === aiMessageId ? { ...msg, text: msg.text + chunk } : msg
                    )
                );
            },
            (error) => {
                console.error("[Chat UI] Stream Error:", error);
                setMessages((prev) =>
                    prev.map((msg) =>
                        msg.id === aiMessageId ? { ...msg, text: "Error: Could not reach the AI service." } : msg
                    )
                );
                setIsLoading(false);
            },
            () => {
                console.log(`[Chat UI] Stream processing completed successfully.`);
                setIsLoading(false);
            }
        );
    };

    const handleKeyDown = (e) => {
        // Submit on Enter (without Shift)
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend(e);
        }
    };

    return (
        <div className="chat-container glass-card">
            <div className="chat-header">
                <h2>Knowledge Base Chat</h2>
                <p>Ask questions about company policies, documentation, and processes.</p>
            </div>

            <div className="chat-messages">
                {messages.map((msg) => (
                    <div key={msg.id} className={`message-wrapper ${msg.sender}`}>
                        <div className={`message-bubble ${msg.sender}`} style={{ whiteSpace: msg.sender === 'user' ? 'pre-wrap' : 'normal' }}>
                            {msg.sender === 'user' ? (
                                <p>{msg.text}</p>
                            ) : (
                                <div className="markdown-body">
                                    <ReactMarkdown>{msg.text}</ReactMarkdown>
                                </div>
                            )}
                        </div>
                    </div>
                ))}
                {isLoading && (
                    <div className="message-wrapper system">
                        <div className="message-bubble system loading-indicator">
                            <span className="dot"></span>
                            <span className="dot"></span>
                            <span className="dot"></span>
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            <form className="chat-input-area" onSubmit={handleSend}>
                <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Type your question... (Shift + Enter for new line)"
                    className="chat-input textarea-input"
                    disabled={isLoading}
                    rows="1"
                />
                <button type="submit" className="btn btn-primary chat-submit" disabled={isLoading || !input.trim()}>
                    Send
                </button>
            </form>
        </div>
    );
};

export default Chat;
