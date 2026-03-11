import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './Auth.css';

const Register = () => {
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [department, setDepartment] = useState('1'); // Maps to a default DB department
    const [passwordStrength, setPasswordStrength] = useState(0);
    const [errorMsg, setErrorMsg] = useState('');
    const { register } = useAuth();
    const navigate = useNavigate();

    const evaluateStrength = (pass) => {
        let score = 0;
        if (!pass) return 0;
        if (pass.length > 6) score += 1;
        if (pass.length > 10) score += 1;
        if (/[A-Z]/.test(pass)) score += 1;
        if (/[0-9]/.test(pass)) score += 1;
        if (/[^A-Za-z0-9]/.test(pass)) score += 1;
        return Math.min(4, score);
    };

    const handlePasswordChange = (e) => {
        const val = e.target.value;
        setPassword(val);
        setPasswordStrength(evaluateStrength(val));
    };

    const getStrengthLabel = (score) => {
        switch (score) {
            case 0: return 'Too Weak';
            case 1: return 'Weak';
            case 2: return 'Fair';
            case 3: return 'Good';
            case 4: return 'Strong';
            default: return '';
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setErrorMsg('');

        // Strict guard matching backend Pydantic validation
        if (password.length < 8 || !/[A-Z]/.test(password) || !/[0-9]/.test(password)) {
            setErrorMsg("Password must be at least 8 characters long and contain at least one uppercase letter and one number.");
            return;
        }

        try {
            await register(name, email, password, department);
            // Optionally, we could pass a success state to the login page
            // For now, simply navigate them back to the login to authenticate
            navigate('/login');
        } catch (error) {
            setErrorMsg(error.message || "Registration failed.");
            console.error("Registration failed", error);
        }
    };

    return (
        <div className="auth-container">
            <div className="auth-card glass-panel">
                <div className="auth-header">
                    <h1 className="text-gradient">Create Account</h1>
                    <p>Join KnowServe and explore company knowledge.</p>
                </div>

                {errorMsg && <div className="status-banner error" style={{ marginBottom: '1rem' }}>{errorMsg}</div>}

                <form onSubmit={handleSubmit} className="auth-form">
                    <div className="form-group">
                        <label htmlFor="name">Full Name</label>
                        <input
                            type="text"
                            id="name"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="John Doe"
                            required
                        />
                    </div>
                    <div className="form-group">
                        <label htmlFor="email">Email Address</label>
                        <input
                            type="email"
                            id="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            placeholder="you@company.com"
                            required
                        />
                    </div>
                    <div className="form-group">
                        <label htmlFor="department">Department</label>
                        <select
                            id="department"
                            value={department}
                            onChange={(e) => setDepartment(e.target.value)}
                            required
                        >
                            <option value="1">Engineering</option>
                            <option value="2">Human Resources</option>
                            <option value="3">Finance</option>
                            <option value="4">Marketing</option>
                            <option value="5">R&D</option>
                        </select>
                    </div>
                    <div className="form-group">
                        <label htmlFor="password">Password</label>
                        <input
                            type="password"
                            id="password"
                            value={password}
                            onChange={handlePasswordChange}
                            placeholder="••••••••"
                            required
                        />
                        {password.length > 0 && (
                            <div className="password-strength">
                                <div className="strength-bar">
                                    <div
                                        className={`strength-fill strength-${passwordStrength}`}
                                        style={{ width: `${(passwordStrength / 4) * 100}%` }}
                                    ></div>
                                </div>
                                <span className={`strength-label text-${passwordStrength}`}>
                                    {getStrengthLabel(passwordStrength)}
                                </span>
                            </div>
                        )}
                    </div>
                    <button type="submit" className="btn btn-primary auth-submit">
                        Register
                    </button>
                </form>

                <div className="auth-footer">
                    <p>Already have an account? <Link to="/login">Sign In</Link></p>
                </div>
            </div>
        </div>
    );
};

export default Register;
