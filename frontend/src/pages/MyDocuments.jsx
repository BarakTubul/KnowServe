import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useDocsContext } from '../context/DocsContext';
import { fetchAccessibleDocsApi } from '../services/api';
import './MyDocuments.css';

const MyDocuments = () => {
    const { user } = useAuth();
    const { documents, setDocuments } = useDocsContext();
    const [isLoading, setIsLoading] = useState(!documents);
    const [error, setError] = useState('');

    // Filtering State
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedDepartment, setSelectedDepartment] = useState('All');

    useEffect(() => {
        if (documents) {
            setIsLoading(false);
            return;
        }

        const loadDocs = async () => {
            try {
                const data = await fetchAccessibleDocsApi();
                setDocuments(data || []);
            } catch (err) {
                console.error("Failed to fetch documents", err);
                setError(err.message || "Failed to retrieve documents");
            } finally {
                setIsLoading(false);
            }
        };

        loadDocs();
    }, [documents, setDocuments]);

    return (
        <div className="docs-container fade-in">
            <div className="docs-header">
                <h1 className="text-gradient">My Documents</h1>
                <p>Welcome, {user?.name}. Here are the documents you have access to.</p>
            </div>

            <div className="glass-card docs-content">
                {isLoading ? (
                    <div className="loading-state">
                        <span className="dot"></span>
                        <span className="dot"></span>
                        <span className="dot"></span>
                    </div>
                ) : documents && documents.length > 0 ? (
                    <>
                        <div className="docs-filter-bar" style={{ display: 'flex', gap: '1rem', padding: '1rem', borderBottom: '1px solid var(--border-glass)', marginBottom: '1rem', alignItems: 'flex-end' }}>
                            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                                <label style={{ fontSize: '0.85rem', fontWeight: 500, color: 'var(--text-muted)' }}>Search Documents</label>
                                <input
                                    type="text"
                                    placeholder="Search by title..."
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                    style={{ padding: '0.6rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-glass)' }}
                                />
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                                <label style={{ fontSize: '0.85rem', fontWeight: 500, color: 'var(--text-muted)' }}>Filter by Department</label>
                                <select
                                    value={selectedDepartment}
                                    onChange={(e) => setSelectedDepartment(e.target.value)}
                                    style={{ padding: '0.6rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-glass)' }}
                                >
                                    {['All', ...new Set((documents || []).flatMap(d => d.allowed_departments || []))].map(dept => (
                                        <option key={dept} value={dept}>{dept}</option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        <div className="docs-list">
                            {(documents || []).filter(doc => {
                                const matchesSearch = doc.title.toLowerCase().includes(searchQuery.toLowerCase());
                                const matchesDept = selectedDepartment === 'All' || (doc.allowed_departments && doc.allowed_departments.includes(selectedDepartment));
                                return matchesSearch && matchesDept;
                            }).map((doc) => (
                                <div key={doc.id} className="doc-item">
                                    <div className="doc-info">
                                        <h4>{doc.title}</h4>
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                                            Visible to: {doc.allowed_departments ? doc.allowed_departments.join(', ') : 'Unknown'}
                                        </div>
                                    </div>
                                    <div className="doc-actions" style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                                        <div className={`doc-status ${doc.status === 'ingested' ? 'status-success' : 'status-error'}`}>
                                            {doc.status}
                                        </div>
                                        {doc.status === 'ingested' && (
                                            <a
                                                href={`/api/documents/my/${doc.id}/download`}
                                                target="_blank"
                                                rel="noreferrer"
                                                className="btn btn-primary btn-sm"
                                            >
                                                View PDF
                                            </a>
                                        )}
                                    </div>
                                </div>
                            ))}
                            {(documents || []).filter(doc => {
                                const matchesSearch = doc.title.toLowerCase().includes(searchQuery.toLowerCase());
                                const matchesDept = selectedDepartment === 'All' || (doc.allowed_departments && doc.allowed_departments.includes(selectedDepartment));
                                return matchesSearch && matchesDept;
                            }).length === 0 && (
                                    <div className="empty-state" style={{ padding: '2rem' }}>
                                        <p>No documents match your filter criteria.</p>
                                    </div>
                                )}
                        </div>
                    </>
                ) : (
                    <div className="empty-state">
                        <p>You don't have access to any documents yet.</p>
                    </div>
                )}
            </div>
        </div>
    );
};

export default MyDocuments;
