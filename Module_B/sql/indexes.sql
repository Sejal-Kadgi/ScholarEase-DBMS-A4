USE scholarease;

-- Index for login (email search)
CREATE INDEX idx_login_email ON login_credentials(Email);

-- Index for session validation
CREATE INDEX idx_session_id ON session(SessionID);
CREATE INDEX idx_session_member ON session(MemberID);

-- Index for scholarship application queries
CREATE INDEX idx_student_id ON scholarship_application(StudentID);

-- Index for payment queries
CREATE INDEX idx_payment_app ON payment(ApplicationID);

-- Index for verification queries
CREATE INDEX idx_verify_app ON verification(ApplicationID);