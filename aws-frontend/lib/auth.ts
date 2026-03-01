import {
  fetchAuthSession,
  getCurrentUser,
  signOut,
} from 'aws-amplify/auth';

/**
 * Retrieve the current Cognito access token as a string.
 * Amplify automatically refreshes tokens when possible.
 * Throws if no valid session exists.
 */
export async function getAccessToken(): Promise<string> {
  const session = await fetchAuthSession();
  const token = session.tokens?.accessToken?.toString();
  if (!token) {
    throw new Error('No access token');
  }
  return token;
}

/**
 * Retrieve the current authenticated user's info including Cognito groups.
 */
export async function getCurrentUserInfo(): Promise<{
  userId: string;
  username: string;
  groups: string[];
}> {
  const [user, session] = await Promise.all([
    getCurrentUser(),
    fetchAuthSession(),
  ]);

  // Try access token payload first, fall back to id token payload
  const accessPayload = session.tokens?.accessToken?.payload;
  const idPayload = session.tokens?.idToken?.payload;

  const groups =
    (accessPayload?.['cognito:groups'] as string[] | undefined) ??
    (idPayload?.['cognito:groups'] as string[] | undefined) ??
    [];

  return {
    userId: user.userId,
    username: user.username,
    groups,
  };
}

/**
 * Returns true if the user belongs to the WafrTeam Cognito group.
 */
export function isTeamUser(groups: string[]): boolean {
  return groups.includes('WafrTeam');
}

/**
 * Sign out the current user from all devices.
 */
export async function signOutUser(): Promise<void> {
  await signOut();
}
