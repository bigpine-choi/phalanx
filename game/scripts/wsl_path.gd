extends RefCounted
## Convert absolute Windows drive paths for the WSL bridge processes.

static func from_windows(path: String) -> String:
	path = path.replace("\\", "/")
	if path.length() < 3 or path[1] != ":":
		return ""
	return "/mnt/" + path[0].to_lower() + path.substr(2)
