import { createContext, useState, useContext, useEffect } from 'react';
import { loginApi, registerApi, logoutApi, fetchMeApi } from '../services/api';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const initializeAuth = async () => {
            try {
                // Instantly try to hydrate user profile from HttpOnly cookie
                const data = await fetchMeApi();
                // We securely recreate the profile linking the HTTPOnly API data with the non-sensitive local name
                const savedName = localStorage.getItem('user_name');
                setUser({ ...data.user, name: savedName });
            } catch (err) {
                // If there's no cookie, or it's expired, we simply stay logged out.
                setUser(null);
            } finally {
                setLoading(false);
            }
        };

        initializeAuth();

        const handleUnauthorized = () => {
            console.warn("Unauthorized API call detected, logging out...");
            logout();
            // Optional: force a page reload to clear memory/state and kick to login nicely
            window.location.href = '/login';
        };

        window.addEventListener('auth:unauthorized', handleUnauthorized);
        return () => window.removeEventListener('auth:unauthorized', handleUnauthorized);
    }, []);

    const login = async (email, password) => {
        const data = await loginApi({ email, password });
        // The HttpOnly cookie is automatically affixed by the backend here.
        // We only persist the user's name to localStorage per strict security requirements.
        localStorage.setItem('user_name', data.user.name);
        setUser(data.user);
    };

    const register = async (name, email, password, department_id) => {
        // Register returns a success message
        await registerApi({ name, email, password, role: 'employee', department_id: parseInt(department_id) });
    };

    const logout = async () => {
        try {
            await logoutApi();
        } catch (err) {
            console.error("Logout API failed silently", err);
        }
        localStorage.removeItem('user_name');
        setUser(null);
    };

    return (
        <AuthContext.Provider value={{ user, loading, login, register, logout }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => useContext(AuthContext);
