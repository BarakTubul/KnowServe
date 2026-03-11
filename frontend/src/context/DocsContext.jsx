import { createContext, useState, useContext } from 'react';

const DocsContext = createContext();

export const DocsProvider = ({ children }) => {
    const [documents, setDocuments] = useState(null);

    return (
        <DocsContext.Provider value={{ documents, setDocuments }}>
            {children}
        </DocsContext.Provider>
    );
};

export const useDocsContext = () => useContext(DocsContext);
