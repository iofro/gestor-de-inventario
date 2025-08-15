package sv.mh.fe.constantes;

import java.io.File;

public class Constantes {

    public static final String DIRECTORY_UPLOADS;

    static {
        String env = System.getenv("CERT_UPLOAD_DIR");
        if (env != null && !env.trim().isEmpty()) {
            String dir = env.trim();
            if (!dir.endsWith("/") && !dir.endsWith("\\")) {
                dir = dir + File.separator;
            }
            DIRECTORY_UPLOADS = dir;
        } else {
            DIRECTORY_UPLOADS = System.getProperty("user.dir") + File.separator + "uploads" + File.separator;
        }
    }
}
