import { createContext, useState, useContext } from 'react';

const ChatContext = createContext();

export const ChatProvider = ({ children }) => {
    const [messages, setMessages] = useState([
        { id: 1, sender: 'system', text: 'Welcome to KnowServe! How can I help you today?' }
    ]);

    // Optional helper to clear memory on logout or when requested
    const clearChat = () => {
        setMessages([
            { id: 1, sender: 'system', text: 'Welcome to KnowServe! How can I help you today?' }
        ]);
    };

    return (
        <ChatContext.Provider value={{ messages, setMessages, clearChat }}>
            {children}
        </ChatContext.Provider>
    );
};

export const useChatContext = () => useContext(ChatContext);
