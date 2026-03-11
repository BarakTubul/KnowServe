import { Outlet, Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Navbar from './Navbar';
import './Layout.css';

const Layout = () => {
    const { user, loading } = useAuth();

    // If no user is logged in, redirect them to the login page.
    if (!user && !loading) {
        return <Navigate to="/login" replace />;
    }

    return (
        <div className="layout">
            <Navbar />
            <main className="main-content">
                <Outlet />
            </main>
        </div>
    );
};

export default Layout;
