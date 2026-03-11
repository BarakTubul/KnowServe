import { useState, useEffect } from 'react';
import { adminUploadApi, fetchAdminDocsApi, updateAdminDocAccessApi, deleteAdminDocApi } from '../services/api';
import './AdminUpload.css';

const AdminUpload = () => {
    const [title, setTitle] = useState('');
    const [sourceUrl, setSourceUrl] = useState('');
    const [selectedDepts, setSelectedDepts] = useState({
        1: false, 2: false, 3: false, 4: false, 5: false
    });
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [statusMsg, setStatusMsg] = useState('');

    // --- List & Edit State ---
    const [docs, setDocs] = useState([]);
    const [isLoadingDocs, setIsLoadingDocs] = useState(true);
    const [editingDocId, setEditingDocId] = useState(null);
    const [editingDepts, setEditingDepts] = useState({});

    // --- Filtering State ---
    const [searchQuery, setSearchQuery] = useState('');

    const fetchDocs = async () => {
        setIsLoadingDocs(true);
        try {
            const data = await fetchAdminDocsApi();
            setDocs(data || []);
        } catch (err) {
            console.error("Failed to load documents", err);
        } finally {
            setIsLoadingDocs(false);
        }
    };

    useEffect(() => {
        fetchDocs();
    }, []);

    const handleDeptToggle = (id) => {
        setSelectedDepts(prev => ({
            ...prev,
            [id]: !prev[id]
        }));
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setIsSubmitting(true);
        setStatusMsg('');

        const allowedDeptIds = Object.entries(selectedDepts)
            .filter(([_, isSelected]) => isSelected)
            .map(([id]) => parseInt(id));

        if (allowedDeptIds.length === 0) {
            setStatusMsg('Error: Please select at least one permitted department.');
            setIsSubmitting(false);
            return;
        }

        try {
            const response = await adminUploadApi({
                title,
                source_url: sourceUrl,
                allowed_department_ids: allowedDeptIds
            });
            setStatusMsg('Success: Document queued for ingestion! Awaiting background worker...');
            setTitle('');
            setSourceUrl('');
            setSelectedDepts({ 1: false, 2: false, 3: false, 4: false, 5: false });
            fetchDocs(); // Refresh list to show as pending immediately

            // Initiate WebSocket connection for live status
            if (response && response.id) {
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const wsUrl = `${protocol}//${window.location.host}/api/ws/documents/${response.id}`;
                const ws = new WebSocket(wsUrl);

                ws.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        console.log("WebSocket event:", data);
                        if (data.status === 'ingested') {
                            setStatusMsg(`Success: Document ID ${data.doc_id} fully ingested!`);
                            fetchDocs(); // Refresh list mapping to show green status
                            ws.close();
                        } else if (data.status === 'failed') {
                            setStatusMsg(`Error: Ingestion failed for ID ${data.doc_id}. ${data.error || ''}`);
                            fetchDocs(); // Refresh to show error status
                            ws.close();
                        }
                    } catch (e) {
                        console.error("WS Parse error", e);
                    }
                };

                ws.onerror = (err) => {
                    console.error("WebSocket Error:", err);
                    ws.close();
                };
            }
        } catch (err) {
            setStatusMsg(`Error: ${err.message || 'Ingestion failed.'}`);
        } finally {
            setIsSubmitting(false);
        }
    };

    const toggleEditAccess = (doc) => {
        if (editingDocId === doc.id) {
            setEditingDocId(null);
        } else {
            setEditingDocId(doc.id);
            // Pre-fill the edit state with current access
            const currentDepts = { 1: false, 2: false, 3: false, 4: false, 5: false };
            (doc.allowed_department_ids || []).forEach(id => {
                currentDepts[id] = true;
            });
            setEditingDepts(currentDepts);
        }
    };

    const handleEditDeptToggle = (id) => {
        setEditingDepts(prev => ({
            ...prev,
            [id]: !prev[id]
        }));
    };

    const saveAccessEdit = async (docId) => {
        const allowedDeptIds = Object.entries(editingDepts)
            .filter(([_, isSelected]) => isSelected)
            .map(([id]) => parseInt(id));

        if (allowedDeptIds.length === 0) {
            alert('Please select at least one permitted department.');
            return;
        }

        try {
            await updateAdminDocAccessApi(docId, allowedDeptIds);
            setEditingDocId(null);
            fetchDocs(); // Refresh list
        } catch (err) {
            alert(`Error: ${err.message || 'Update failed.'}`);
        }
    };

    const handleDeleteDoc = async (docId, docTitle) => {
        if (!window.confirm(`Are you sure you want to completely delete "${docTitle}"? This cannot be undone.`)) {
            return;
        }

        try {
            await deleteAdminDocApi(docId);
            setStatusMsg(`Success: Document "${docTitle}" has been deleted.`);
            fetchDocs(); // Refresh list
        } catch (err) {
            alert(`Error: ${err.message || 'Deletion failed.'}`);
        }
    };

    const departments = [
        { id: 1, name: "Engineering" },
        { id: 2, name: "Human Resources" },
        { id: 3, name: "Finance" },
        { id: 4, name: "Marketing" },
        { id: 5, name: "R&D" }
    ];

    return (
        <div className="admin-container fade-in">
            <div className="admin-header">
                <h1 className="text-gradient">Document Management</h1>
                <p>Upload files or supply external links to embed into the company vector store.</p>
            </div>

            <div className="admin-content">
                <div className="glass-card upload-card">
                    <h3>Ingest New Document</h3>

                    {statusMsg && (
                        <div className={`status-banner ${statusMsg.includes('Error') ? 'error' : 'success'}`}>
                            {statusMsg}
                        </div>
                    )}

                    <form onSubmit={handleSubmit} className="upload-form">
                        <div className="form-group">
                            <label htmlFor="docTitle">Document Title</label>
                            <input
                                id="docTitle"
                                type="text"
                                value={title}
                                onChange={(e) => setTitle(e.target.value)}
                                placeholder="e.g. Q4 Financial Report"
                                required
                            />
                        </div>

                        <div className="form-group">
                            <label htmlFor="sourceUrl">Source URL (Google Drive/Public PDF)</label>
                            <input
                                id="sourceUrl"
                                type="url"
                                value={sourceUrl}
                                onChange={(e) => setSourceUrl(e.target.value)}
                                placeholder="https://..."
                                required
                            />
                        </div>

                        <div className="form-group">
                            <label>Permitted Departments</label>
                            <p className="field-help">Which departments can view this document?</p>
                            <div className="dept-grid">
                                {departments.map(dept => (
                                    <label key={dept.id} className="dept-checkbox">
                                        <input
                                            type="checkbox"
                                            checked={selectedDepts[dept.id]}
                                            onChange={() => handleDeptToggle(dept.id)}
                                        />
                                        <span className="checkmark"></span>
                                        {dept.name}
                                    </label>
                                ))}
                            </div>
                        </div>

                        <button type="submit" className="btn btn-primary submit-btn" disabled={isSubmitting}>
                            {isSubmitting ? 'Processing...' : 'Ingest Document'}
                        </button>
                    </form>
                </div>

                <div className="glass-card list-card">
                    <h3>Recent Uploads</h3>

                    <div className="admin-filter-bar" style={{ marginBottom: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                        <label style={{ fontSize: '0.85rem', fontWeight: 500, color: 'var(--text-muted)' }}>Search Local Documents</label>
                        <input
                            type="text"
                            placeholder="Type a title to search..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            style={{ width: '100%', padding: '0.6rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-glass)' }}
                        />
                    </div>

                    {isLoadingDocs ? (
                        <div className="loading-state">
                            <span className="dot"></span><span className="dot"></span><span className="dot"></span>
                        </div>
                    ) : docs.length > 0 ? (
                        <div className="admin-docs-list">
                            {docs.filter(doc => doc.title.toLowerCase().includes(searchQuery.toLowerCase())).map(doc => (
                                <div key={doc.id} className="admin-doc-item">
                                    <div className="admin-doc-header">
                                        <div className="admin-doc-info">
                                            <h4>{doc.title}</h4>
                                            <span className={`doc-status status-${doc.status === 'ingested' ? 'success' : doc.status === 'error' ? 'error' : 'pending'}`}>
                                                {doc.status}
                                            </span>
                                        </div>
                                        <div className="admin-doc-actions" style={{ display: 'flex', gap: '0.5rem' }}>
                                            <button
                                                className="btn btn-secondary btn-sm"
                                                onClick={() => toggleEditAccess(doc)}
                                            >
                                                {editingDocId === doc.id ? 'Cancel Edit' : 'Edit Access'}
                                            </button>
                                            <button
                                                className="btn btn-sm"
                                                style={{ backgroundColor: 'transparent', color: '#ff4d4f', border: '1px solid #ff4d4f' }}
                                                onClick={() => handleDeleteDoc(doc.id, doc.title)}
                                            >
                                                Delete
                                            </button>
                                        </div>
                                    </div>

                                    {editingDocId === doc.id ? (
                                        <div className="admin-doc-edit-panel">
                                            <p className="field-help" style={{ marginBottom: '0.5rem' }}>Update Accessible Departments:</p>
                                            <div className="dept-grid">
                                                {departments.map(dept => (
                                                    <label key={dept.id} className="dept-checkbox">
                                                        <input
                                                            type="checkbox"
                                                            checked={editingDepts[dept.id] || false}
                                                            onChange={() => handleEditDeptToggle(dept.id)}
                                                        />
                                                        <span className="checkmark"></span>
                                                        {dept.name}
                                                    </label>
                                                ))}
                                            </div>
                                            <div style={{ marginTop: '1rem', display: 'flex', justifyContent: 'flex-end' }}>
                                                <button className="btn btn-primary btn-sm" onClick={() => saveAccessEdit(doc.id)}>Save Access</button>
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="admin-doc-departments">
                                            <strong>Visible to: </strong>
                                            {doc.allowed_departments && doc.allowed_departments.length > 0
                                                ? doc.allowed_departments.join(", ")
                                                : "None"}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="empty-state">
                            <p>No documents uploaded yet.</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default AdminUpload;
