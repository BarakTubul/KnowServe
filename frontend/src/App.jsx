import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { ChatProvider } from './context/ChatContext';
import { DocsProvider } from './context/DocsContext';
import Layout from './components/Layout';
import Login from './pages/Login';
import Register from './pages/Register';
import Chat from './pages/Chat';
import AdminUpload from './pages/AdminUpload';
import MyDocuments from './pages/MyDocuments';

function App() {
  return (
    <AuthProvider>
      <Router>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />

          <Route path="/" element={
            <ChatProvider>
              <DocsProvider>
                <Layout />
              </DocsProvider>
            </ChatProvider>
          }>
            <Route index element={<Navigate to="/chat" replace />} />
            <Route path="chat" element={<Chat />} />
            <Route path="my-docs" element={<MyDocuments />} />
            <Route path="admin/upload" element={<AdminUpload />} />
          </Route>
        </Routes>
      </Router>
    </AuthProvider>
  );
}

export default App;
