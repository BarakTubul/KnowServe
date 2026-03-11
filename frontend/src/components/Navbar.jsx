import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './Navbar.css';

const Navbar = () => {
    const { user, logout } = useAuth();
    const navigate = useNavigate();

    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    return (
        <header className="navbar glass-panel">
            <div className="navbar-brand">
                <Link to="/" className="logo text-gradient">KnowServe</Link>
            </div>

            <nav className="navbar-menu">
                {user ? (
                    <>
                        <Link to="/chat" className="nav-link">Chat</Link>
                        <Link to="/my-docs" className="nav-link">My Documents</Link>
                        {user.role === 'admin' && (
                            <Link to="/admin/upload" className="nav-link">Manage Docs</Link>
                        )}
                        <div className="user-profile">
                            <span className="user-email">{user.name || user.email}</span>
                            <button className="btn btn-ghost btn-logout" onClick={handleLogout}>
                                Logout
                            </button>
                        </div>
                    </>
                ) : (
                    <>
                        <Link to="/login" className="nav-link">Login</Link>
                    </>
                )}
            </nav>
        </header>
    );
};

export default Navbar;
